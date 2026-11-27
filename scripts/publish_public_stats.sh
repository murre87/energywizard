#!/bin/bash
# Körs av crontab varje natt - räknar om besparingssiffrorna och pushar docs/data/stats.json och utrustning.json till main.
# Bara datafiler, ingen kod - se scripts/export_public_stats.py och PR #17 för resonemang/formel.
#
# Git-delen går i en egen ren klon (PUB). Förut körde skriptet i driftkatalogen, som står på en Cursor-gren: committen
# hamnade där och "git push origin main" avvisades varje natt (non-fast-forward), så den publika sidan visade siffror från
# 2026-11-13 medan webben visade dagens (#616).
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
PUB="${PUB_DIR:-/home/emil/opt/ew-pages}"
REMOTE="${PUB_REMOTE:-https://github.com/murre87/energywizard.git}"
GIT=(git -c user.name=murre87 -c user.email=17743298+murre87@users.noreply.github.com)

[ -d "$PUB/.git" ] || git clone --quiet "$REMOTE" "$PUB"
cd "$PUB"
git fetch --quiet origin main
git checkout --quiet main
git reset --quiet --hard origin/main

docker cp "$PUB/scripts/export_public_stats.py" smartbox:/tmp/export_public_stats.py
docker exec smartbox python3 /tmp/export_public_stats.py
docker exec smartbox cat /docs/data/stats.json > "$PUB/docs/data/stats.json"

# Märken som körs hos installationerna (anonym telemetri, bara tillverkare och antal)
TELEMETRY_STATS_URL=$(docker exec webdashboard printenv TELEMETRY_STATS_URL) \
TELEMETRY_STATS_TOKEN=$(docker exec webdashboard printenv TELEMETRY_STATS_TOKEN) \
    python3 "$PUB/scripts/export_public_equipment.py" || echo "Utrustningslistan kunde inte uppdateras, behåller förra."

if git diff --quiet -- docs/data/stats.json docs/data/utrustning.json; then
    echo "Inga ändrade siffror, hoppar över commit."
    exit 0
fi

git add docs/data/stats.json docs/data/utrustning.json
"${GIT[@]}" commit --quiet -m "Uppdatera publika besparingssiffror ($(date +%Y-%m-%d))"
for i in 1 2 3 4; do                                  # andra pushar till main under tiden: hämta och försök igen
    if git push --quiet origin main; then
        echo "Publicerat $(date -Is)"
        exit 0
    fi
    git fetch --quiet origin main
    "${GIT[@]}" rebase --quiet origin/main
done
echo "Kunde inte pusha efter fyra försök" >&2
exit 1
