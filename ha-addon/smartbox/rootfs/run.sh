#!/bin/bash
# Enkel startsekvens (inte s6-overlay - se Dockerfile-kommentaren för varför):
# initiera/starta en lokal Postgres i den här containern, vänta tills den
# svarar, sätt sedan samma POSTGRES_*-miljövariabler som den vanliga
# docker-compose-driften redan förväntar sig, och kör huvudloopen oförändrad.
set -e

export PGDATA="/config/pgdata"
export POSTGRES_HOST="localhost"
export POSTGRES_USER="${POSTGRES_USER:-smartbox}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-smartbox}"
export POSTGRES_DB="${POSTGRES_DB:-smartbox}"
export HOUSE_CONFIG_PATH="/config/house_config.yaml"
export TELEMETRY_OPT_IN="${TELEMETRY_OPT_IN:-false}"
export TELEMETRY_ENDPOINT="${TELEMETRY_ENDPOINT:-}"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    echo "🐘 Första start - initierar lokal Postgres i $PGDATA"
    mkdir -p "$PGDATA"
    chown -R postgres:postgres "$PGDATA"
    su postgres -c "/usr/lib/postgresql/*/bin/initdb -D '$PGDATA'"
fi

chown -R postgres:postgres "$PGDATA"
su postgres -c "/usr/lib/postgresql/*/bin/pg_ctl -D '$PGDATA' -l /tmp/postgres.log -w start"

su postgres -c "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"" | grep -q 1 \
    || su postgres -c "psql -c \"CREATE USER ${POSTGRES_USER} WITH PASSWORD '${POSTGRES_PASSWORD}'\""
su postgres -c "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"" | grep -q 1 \
    || su postgres -c "psql -c \"CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER}\""

echo "🔆 Startar EnergyWizard (smartbox)..."
exec python -u main.py
