#!/bin/bash
# Körs av crontab (1 gång/månad) - räknar om besparingssiffrorna och pushar
# docs/data/stats.json till main. Bara en datafil, ingen kod - se
# scripts/export_public_stats.py och PR #17 för resonemang/formel.
set -euo pipefail
cd /home/emil/opt/Energywizz

docker cp scripts/export_public_stats.py smartbox:/tmp/export_public_stats.py
docker exec smartbox python3 /tmp/export_public_stats.py
docker exec smartbox cat /docs/data/stats.json > docs/data/stats.json

if git diff --quiet -- docs/data/stats.json; then
    echo "Inga ändrade siffror, hoppar över commit."
    exit 0
fi

git add docs/data/stats.json
git commit -m "Uppdatera publika besparingssiffror ($(date +%Y-%m-%d))"
git push origin main
