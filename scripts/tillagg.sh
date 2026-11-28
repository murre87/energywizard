#!/bin/bash
# Tilläggets version efter en byggd bild (flyttad hit från .github/workflows/docker.yml, jobbet "tillagg", så att den går att testa).
#   scripts/tillagg.sh <commit-sha> [bild]
# Körs i en utcheckning av main. Taggar bilden <bild>:<sha> med tilläggets version och höjer versionen i config.yaml, i den ordningen:
# ingen användare ska se en uppdatering vars bild inte finns än. Versionstaggar skrivs aldrig om.
#
# Två lägen:
#  - Utan fragment i changelog.d/ i den byggda commiten: versionen är den som står överst i CHANGELOG.md i commiten (som förut).
#  - Med fragment: de slås ihop till nästa version överst i CHANGELOG.md (översta versionen på senaste main + 1), fragmenten tas bort och
#    config.yaml höjs, i en enda commit. Bara fragment som fanns i den byggda commiten räknas, så fragment från en senare merge väntar på sin egen bild.
set -eu
SHA=$1
IMG=${2:-ghcr.io/murre87/energywizard}
AV=ha-addon/smartbox/addon_version.py
CL=ha-addon/smartbox/CHANGELOG.md

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

digest() { docker buildx imagetools inspect --format '{{.Manifest.Digest}}' "$1" 2>/dev/null || true; }

# tag_image <version>: taggar $IMG:$SHA som $IMG:<version>. Skriver aldrig om en tagg som pekar på en annan bild (returnerar 2 då).
tag_image() {
  if docker buildx imagetools inspect "$IMG:$1" >/dev/null 2>&1; then
    if [ "$(digest "$IMG:$1")" = "$(digest "$IMG:$SHA")" ]; then echo "$IMG:$1 finns redan (samma bild)"; return 0; fi
    return 2
  fi
  docker buildx imagetools create -t "$IMG:$1" "$IMG:$SHA"
  docker buildx imagetools inspect "$IMG:$1" | grep -q "linux/arm64"
}

FRAGS=$(git ls-tree -r --name-only "$SHA" -- changelog.d | grep -E '^changelog\.d/.+\.md$' | grep -v '^changelog\.d/README\.md$' || true)

if [ -z "$FRAGS" ]; then
  # Versionen som den HÄR körningens bild hör till: CHANGELOG i den byggda commiten
  TMP=$(mktemp)
  git show "$SHA:$CL" > "$TMP"
  NEW=$(python3 $AV changelog "$TMP")
  echo "Bildens version: $NEW"
  if tag_image "$NEW"; then :; else
    echo "$IMG:$NEW finns redan men är en annan bild - skrivs inte om"
    docker buildx imagetools inspect "$IMG:$NEW" | grep -q "linux/arm64"
  fi
  for i in 1 2 3 4 5; do
    git fetch -q origin main && git reset -q --hard origin/main
    CUR=$(python3 $AV config)
    if ! python3 $AV newer "$NEW" "$CUR"; then
      echo "config.yaml har redan $CUR (>= $NEW) - inget att höja"; exit 0
    fi
    python3 $AV set "$NEW" "$IMG"
    git commit -qam "Tillägg $NEW: färdig bild publicerad ($IMG:$NEW)"
    if git push -q origin HEAD:main; then echo "config.yaml höjd till $NEW"; exit 0; fi
    sleep $((2 ** i))
  done
  echo "Kunde inte höja config.yaml till $NEW"; exit 1
fi

for i in 1 2 3 4 5; do
  git fetch -q origin main && git reset -q --hard origin/main
  USE=""
  for f in $FRAGS; do [ -f "$f" ] && USE="$USE $f"; done
  if [ -z "$USE" ]; then echo "Fragmenten i den här commiten är redan inräknade i en tidigare version - inget att göra"; exit 0; fi
  NEW=$(python3 $AV next)
  for n in 1 2 3 4 5; do                       # en tagg som redan pekar på en annan bild (kvarlevande från ett misslyckat försök) hoppas över
    rc=0; tag_image "$NEW" || rc=$?
    [ "$rc" = 0 ] && break
    [ "$rc" = 2 ] || exit "$rc"
    echo "$IMG:$NEW är en annan bild - tar nästa version"
    NEW=$(python3 $AV succ "$NEW")
  done
  [ "$rc" = 0 ] || { echo "Hittade ingen ledig version"; exit 1; }
  echo "Bildens version: $NEW (fragment:$USE)"
  # shellcheck disable=SC2086
  python3 $AV compile "$NEW" "$(TZ=Europe/Stockholm date +%F)" $USE
  # shellcheck disable=SC2086
  git rm -q $USE
  python3 $AV set "$NEW" "$IMG"
  git add ha-addon/smartbox
  git commit -qm "Tillägg $NEW: färdig bild publicerad ($IMG:$NEW), ändringslogg ihopslagen"
  if git push -q origin HEAD:main; then echo "config.yaml höjd till $NEW"; exit 0; fi
  sleep $((2 ** i))
done
echo "Kunde inte höja config.yaml"; exit 1
