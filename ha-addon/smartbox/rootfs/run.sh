#!/bin/bash
# Enkel startsekvens (inte s6-overlay - se Dockerfile-kommentaren för varför):
#   1. läs tilläggets inställningar (/data/options.json, skriven av Supervisor)
#   2. initiera/starta en lokal Postgres i den här containern
#   3. starta gränssnitten (ewapp :8502, webdashboard :8503) i bakgrunden, med omstart
#   4. kör huvudloopen (smartbox) i förgrunden - dör den, dör tillägget och Supervisor
#      startar om det (boot: auto), precis som restart: unless-stopped i docker-compose.
set -e

# Supervisor skickar INTE tilläggets inställningar som miljövariabler - de ligger i
# /data/options.json. Tidigare lästes de aldrig, så telemetri-reglaget i tilläggets
# UI hade ingen effekt. Python finns redan i bilden (ingen jq/bashio behövs).
OPTIONS="/data/options.json"
opt() {
    python3 -c 'import json,sys
try:
    v = json.load(open(sys.argv[1])).get(sys.argv[2])
except Exception:
    v = None
print("" if v is None else (str(v).lower() if isinstance(v, bool) else v))' "$OPTIONS" "$1"
}
if [ -f "$OPTIONS" ]; then
    # Telemetrin är obligatorisk sedan 1.2.45 (se README): telemetry_opt_in/anonymous_ping/telemetry_endpoint läses inte.
    export DASHBOARD_PASSWORD="$(opt dashboard_password)"
    # Flottvy Installationer (#265): valfri URL+token till samlarens /api/stats — på DENNA installation,
    # så support ser alla hus anonymt utan att logga in på någon annans webb.
    v="$(opt telemetry_stats_url)"; [ -n "$v" ] && export TELEMETRY_STATS_URL="$v"
    v="$(opt telemetry_stats_token)"; [ -n "$v" ] && export TELEMETRY_STATS_TOKEN="$v"
    # NIBE lokalt REST-API (heat_pump.driver: nibe_local) - bara de som är ifyllda (#138)
    for k in username password tls_pin_sha256; do
        v="$(opt nibe_local_$k)"
        if [ -n "$v" ]; then export "NIBE_LOCAL_$(echo "$k" | tr a-z A-Z)=$v"; fi
    done
fi

# Som HA-tillägg ligger databas och house_config.yaml i /config (tilläggets egen mapp).
# Fristående (docker run / compose utan Supervisor) ligger allt i /data, som monteras från värden.
if [ -n "$SUPERVISOR_TOKEN" ] || { [ -d /config ] && [ -f "$OPTIONS" ]; }; then
    EW_HOME="/config"
else
    EW_HOME="/data"
fi
mkdir -p "$EW_HOME"
export PGDATA="$EW_HOME/pgdata"
export POSTGRES_HOST="localhost"
export POSTGRES_USER="${POSTGRES_USER:-smartbox}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-smartbox}"
export POSTGRES_DB="${POSTGRES_DB:-smartbox}"
export HOUSE_CONFIG_PATH="$EW_HOME/house_config.yaml"
export HOUSE_CONFIG_WRITABLE=1        # entitetsväljarens "Spara och starta"
export EW_SETTINGS_PATH="/data/energywizard.json"   # startguidens lösenord och HA-anslutning
[ -f "$HOUSE_CONFIG_PATH" ] || printf 'house_id: "mitt-hus"\n' > "$HOUSE_CONFIG_PATH"
export DASHBOARD_PASSWORD="${DASHBOARD_PASSWORD:-}"
# webdashboard proxar ewapps styrkommandon internt (i compose: http://ewapp:8502).
export EWAPP_URL="http://127.0.0.1:8502"
export PYTHONUNBUFFERED=1

# Startmeddelandena på installationens språk (som i18n_py.py): valt i EnergyWizard, annars Home Assistants, annars svenska.
EW_LANG="$(python3 -c 'import json,os,sys,urllib.request
lang = None
try:
    lang = json.load(open(os.environ.get("EW_SETTINGS_PATH", "/data/energywizard.json"))).get("language")
except Exception:
    pass
if not lang and os.environ.get("SUPERVISOR_TOKEN"):
    try:
        r = urllib.request.Request("http://supervisor/core/api/config", headers={"Authorization": "Bearer " + os.environ["SUPERVISOR_TOKEN"]})
        lang = json.load(urllib.request.urlopen(r, timeout=5)).get("language")
    except Exception:
        pass
print(str(lang or "sv").split("-")[0].lower())' 2>/dev/null || echo sv)"
say() { if [ "$EW_LANG" = "sv" ]; then echo "$1"; else echo "$2"; fi; }

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    say "🐘 Första start - initierar lokal Postgres i $PGDATA" "🐘 First start - initialising the local Postgres in $PGDATA"
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su postgres -c "/usr/lib/postgresql/*/bin/initdb -D '$PGDATA'"
fi

chown -R postgres:postgres "$PGDATA"
su postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D '$PGDATA' -l /tmp/postgres.log -w start"
# #194: skona minneskortet (Raspberry Pi/HA Green). Skrivningarna samlas i stället för att tvingas ut till kortet vid
# varje rad (minutloggen, journalen). Vid strömavbrott kan de sista sekundernas loggrader gå förlorade, aldrig mer.
su postgres -c "psql -q -c \"ALTER SYSTEM SET synchronous_commit = off\" -c \"ALTER SYSTEM SET wal_writer_delay = '10s'\" -c \"ALTER SYSTEM SET checkpoint_timeout = '15min'\" -c \"SELECT pg_reload_conf()\"" >/dev/null || true

su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"" | grep -q 1 \
    || su postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}'\""
su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"" | grep -q 1 \
    || su postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER}\""

# Ett gränssnitt som kraschar startas om efter 5 s - det får aldrig ta ner motorn.
keep_running() {
    local name="$1" dir="$2" port="$3"
    ( while true; do
        say "🌐 Startar $name på port $port..." "🌐 Starting $name on port $port..."
        (cd "$dir" && python -m uvicorn app:app --host 0.0.0.0 --port "$port") || true
        say "⚠️ $name avslutades - startar om om 5 s." "⚠️ $name stopped - restarting in 5 s."
        sleep 5
      done ) &
}

# Utan lösenord öppnar webben startguiden, där lösenordet väljs - gränssnitten startas alltid.
keep_running "$(say "mobilappen (ewapp)" "the mobile app (ewapp)")" /ewapp 8502
keep_running "webdashboard" /webdashboard 8503
say "👉 Öppna http://<den här datorns adress>:8503 för att komma igång." "👉 Open http://<this computer's address>:8503 to get started."

say "🔆 Startar EnergyWizard (smartbox)..." "🔆 Starting EnergyWizard (smartbox)..."
cd /smartbox
exec python -u main.py
