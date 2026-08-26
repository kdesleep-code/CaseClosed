#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
GENERATED_DIR="$SCRIPT_DIR/generated"
START_SERVICES=0
GENERATE_ONLY=0

usage() {
  cat <<'EOF'
Usage: ./deploy/systemd/install.sh [--generate-only] [--start]

Generate environment-specific systemd units, install them, and enable
CaseClosed at boot. Pass --start to restart the services immediately.
Pass --generate-only to render and verify units without installing them.

Optional environment variables:
  CASECLOSED_SERVICE_USER   Service user (default: current user)
  CASECLOSED_SERVICE_GROUP  Service group (default: user's primary group)
  NPM_BIN                   npm executable (default: command -v npm)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start)
      START_SERVICES=1
      shift
      ;;
    --generate-only)
      GENERATE_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

SERVICE_USER="${CASECLOSED_SERVICE_USER:-$(id -un)}"
SERVICE_GROUP="${CASECLOSED_SERVICE_GROUP:-$(id -gn "$SERVICE_USER")}"
USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
NPM_EXECUTABLE="${NPM_BIN:-$(command -v npm)}"

if [[ -z "$USER_HOME" ]]; then
  echo "Could not determine the home directory for $SERVICE_USER." >&2
  exit 1
fi

if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
  echo "Backend runner not found: $ROOT_DIR/.venv/bin/uvicorn" >&2
  exit 1
fi

if [[ ! -x "$NPM_EXECUTABLE" ]]; then
  echo "npm executable not found: $NPM_EXECUTABLE" >&2
  exit 1
fi

escape_replacement() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//&/\\&}"
  value="${value//|/\\|}"
  printf '%s' "$value"
}

render_unit() {
  local source="$1"
  local destination="$2"
  local escaped_user escaped_group escaped_root escaped_home escaped_npm
  escaped_user="$(escape_replacement "$SERVICE_USER")"
  escaped_group="$(escape_replacement "$SERVICE_GROUP")"
  escaped_root="$(escape_replacement "$ROOT_DIR")"
  escaped_home="$(escape_replacement "$USER_HOME")"
  escaped_npm="$(escape_replacement "$NPM_EXECUTABLE")"

  sed \
    -e "s|@CASECLOSED_SERVICE_USER@|$escaped_user|g" \
    -e "s|@CASECLOSED_SERVICE_GROUP@|$escaped_group|g" \
    -e "s|@CASECLOSED_ROOT@|$escaped_root|g" \
    -e "s|@CASECLOSED_USER_HOME@|$escaped_home|g" \
    -e "s|@NPM_BIN@|$escaped_npm|g" \
    "$source" > "$destination"
}

mkdir -p "$GENERATED_DIR"
render_unit "$SCRIPT_DIR/caseclosed-backend.service.in" "$GENERATED_DIR/caseclosed-backend.service"
render_unit "$SCRIPT_DIR/caseclosed-frontend.service.in" "$GENERATED_DIR/caseclosed-frontend.service"
render_unit "$SCRIPT_DIR/caseclosed-service-restart.sudoers.in" "$GENERATED_DIR/caseclosed-service-restart.sudoers"

systemd-analyze verify \
  "$GENERATED_DIR/caseclosed-backend.service" \
  "$GENERATED_DIR/caseclosed-frontend.service"
/usr/sbin/visudo -cf "$GENERATED_DIR/caseclosed-service-restart.sudoers"

if [[ "$GENERATE_ONLY" == "1" ]]; then
  echo "Generated and verified local units: $GENERATED_DIR"
  exit 0
fi

sudo install -o root -g root -m 0644 \
  "$GENERATED_DIR/caseclosed-backend.service" \
  /etc/systemd/system/caseclosed-backend.service
sudo install -o root -g root -m 0644 \
  "$GENERATED_DIR/caseclosed-frontend.service" \
  /etc/systemd/system/caseclosed-frontend.service
sudo install -o root -g root -m 0440 \
  "$GENERATED_DIR/caseclosed-service-restart.sudoers" \
  /etc/sudoers.d/caseclosed-service-restart
sudo systemctl daemon-reload
sudo systemctl enable caseclosed-backend.service caseclosed-frontend.service

if [[ "$START_SERVICES" == "1" ]]; then
  sudo systemctl restart caseclosed-backend.service caseclosed-frontend.service
fi

echo "Installed and enabled CaseClosed systemd services."
echo "Generated local units (Git-ignored): $GENERATED_DIR"
