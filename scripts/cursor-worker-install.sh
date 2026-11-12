#!/usr/bin/env bash
# Cursor på NUC:en. Kör en gång som emil:
#   bash /home/emil/opt/Energywizz/scripts/cursor-worker-install.sh
# Tjänsten startar vid boot, startar om om processen dör, och pekar på den här
# checkouten (murre87/energywizard, mappen heter Energywizz).
set -euo pipefail

ROOT="/home/emil/opt/Energywizz"
UNIT_NAME="cursor-worker.service"
UNIT_PATH="/etc/systemd/system/${UNIT_NAME}"

if [[ "$(id -un)" != "emil" ]]; then
  echo "Kör scriptet som emil på NUC:en, inte som $(id -un)." >&2
  exit 1
fi
if [[ ! -d "${ROOT}/.git" ]]; then
  echo "Hittar ingen git-checkout i ${ROOT}." >&2
  exit 1
fi

remote="$(git -C "$ROOT" remote get-url origin)"
case "$remote" in
  *murre87/energywizard*) ;;
  *)
    echo "origin i ${ROOT} är ${remote}, väntade murre87/energywizard." >&2
    exit 1
    ;;
esac

AGENT="${HOME}/.local/bin/agent"
if [[ ! -x "$AGENT" ]]; then
  echo "Installerar Cursor CLI till ${AGENT}."
  curl -fsSL https://cursor.com/install | bash
fi
if [[ ! -x "$AGENT" ]]; then
  echo "Cursor CLI saknas fortfarande: ${AGENT}." >&2
  exit 1
fi

help_text="$("$AGENT" worker start --help 2>&1 || true)"
prefix=("$AGENT" worker)
if grep -q -- '--connect-workspace' <<<"$help_text"; then
  prefix+=(--connect-workspace)
fi
prefix+=(start --name nuc --worker-dir "$ROOT")
if grep -q -- '--idle-release-timeout' <<<"$help_text"; then
  prefix+=(--idle-release-timeout 0)
fi

exec_start="${prefix[*]}"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
cat >"$tmp" <<EOF
[Unit]
Description=Cursor worker för Energywizz
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
User=emil
Group=emil
WorkingDirectory=${ROOT}
Environment=HOME=/home/emil
Environment=PATH=/home/emil/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=${exec_start}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Skriver ${UNIT_PATH}"
echo "ExecStart=${exec_start}"
sudo tee "$UNIT_PATH" >/dev/null <"$tmp"
sudo systemctl daemon-reload
sudo systemctl enable "$UNIT_NAME"

if pgrep -u emil -f '[a]gent worker' >/dev/null 2>&1 \
  && ! systemctl is-active --quiet "$UNIT_NAME"; then
  echo "En Cursor-worker körs redan utanför systemd. Tjänsten är påslagen och tar över vid nästa omstart."
  echo "När den gamla processen är stoppad: sudo systemctl start ${UNIT_NAME}"
else
  sudo systemctl restart "$UNIT_NAME"
fi

if systemctl list-unit-files docker.service >/dev/null 2>&1; then
  sudo systemctl enable docker.service
fi

systemctl is-enabled "$UNIT_NAME"
systemctl is-active "$UNIT_NAME" || true
systemctl status "$UNIT_NAME" --no-pager -l || true
echo "Klar. I Cursor väljer du maskinen nuc, checkout ${ROOT}."
