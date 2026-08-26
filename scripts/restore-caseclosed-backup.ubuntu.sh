#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_PATH="${1:-}"
if [[ -z "$BACKUP_PATH" || ! -f "$BACKUP_PATH" ]]; then
  echo "Usage: $0 /path/to/caseclosed-....ccbackup" >&2
  exit 2
fi
if [[ ! -f "$ROOT_DIR/.env" ]]; then
  echo "Missing $ROOT_DIR/.env. Restore never copies .env; create it before continuing." >&2
  exit 2
fi
if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT_DIR/.venv"
fi
if ! "$ROOT_DIR/.venv/bin/python" -c "import caseclosed, cryptography" 2>/dev/null; then
  "$ROOT_DIR/.venv/bin/pip" install -e "$ROOT_DIR/backend[dev]"
fi
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  (cd "$ROOT_DIR/frontend" && npm ci)
fi

read -r -s -p "Backup passphrase: " PASSPHRASE
echo
PASS_FILE="$(mktemp)"
STATUS_FILE="$ROOT_DIR/.tmp/usb-backup-operations/manual-restore-$(date +%s).json"
trap 'rm -f "$PASS_FILE"' EXIT
chmod 600 "$PASS_FILE"
printf '%s' "$PASSPHRASE" > "$PASS_FILE"
unset PASSPHRASE

cd "$ROOT_DIR"
"$ROOT_DIR/.venv/bin/python" -m caseclosed.services.usb_backup restore \
  --backup-path "$BACKUP_PATH" \
  --passphrase-file "$PASS_FILE" \
  --status-file "$STATUS_FILE"
./scripts/restart-caseclosed-services.ubuntu.sh
echo "Restore completed. Status: $STATUS_FILE"
