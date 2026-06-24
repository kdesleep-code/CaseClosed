#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/.tmp/dev-server-logs"

BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-8443}"
TMUX_SESSION="${TMUX_SESSION:-caseclosed-dev}"
NO_HTTPS="${NO_HTTPS:-0}"

mkdir -p "$LOG_DIR"

usage() {
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --backend-host HOST     Backend bind host (default: $BACKEND_HOST)
  --backend-port PORT     Backend port (default: $BACKEND_PORT)
  --frontend-host HOST    Frontend bind host (default: $FRONTEND_HOST)
  --frontend-port PORT    Frontend port (default: $FRONTEND_PORT)
  --session NAME          tmux session name (default: $TMUX_SESSION)
  --no-https              Force Vite HTTP mode
  -h, --help              Show this help

Environment variables with the same uppercase names are also supported.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend-host)
      BACKEND_HOST="$2"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="$2"
      shift 2
      ;;
    --frontend-host)
      FRONTEND_HOST="$2"
      shift 2
      ;;
    --frontend-port)
      FRONTEND_PORT="$2"
      shift 2
      ;;
    --session)
      TMUX_SESSION="$2"
      shift 2
      ;;
    --no-https)
      NO_HTTPS=1
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

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 1
  fi
}

port_pids() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "$port" 2>/dev/null || true
    return
  fi
  ss -ltnp "sport = :$port" 2>/dev/null |
    sed -n 's/.*pid=\([0-9]\+\).*/\1/p' |
    sort -u || true
}

stop_port() {
  local port="$1"
  local name="$2"
  local pids
  pids="$(port_pids "$port" | tr '\n' ' ')"
  if [[ -z "${pids// }" ]]; then
    echo "$name: no process is listening on port $port."
    return
  fi

  echo "$name: stopping old process(es) on port $port: $pids"
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true

  for _ in {1..40}; do
    sleep 0.25
    pids="$(port_pids "$port" | tr '\n' ' ')"
    if [[ -z "${pids// }" ]]; then
      echo "$name: confirmed no old process remains on port $port."
      return
    fi
  done

  echo "$name: force stopping remaining process(es) on port $port: $pids"
  # shellcheck disable=SC2086
  kill -9 $pids 2>/dev/null || true
}

wait_http_ok() {
  local url="$1"
  local name="$2"
  local insecure_flag=()
  if [[ "$url" == https://* ]]; then
    insecure_flag=(-k)
  fi

  for _ in {1..60}; do
    local code
    code="$(curl "${insecure_flag[@]}" -sS -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || true)"
    if [[ "$code" =~ ^[234][0-9][0-9]$ ]]; then
      echo "$name: ready ($code) $url"
      return
    fi
    sleep 0.5
  done

  echo "$name: did not become ready: $url" >&2
  return 1
}

require_command tmux
require_command curl
require_command ss

if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
  echo "Expected backend runner not found: $ROOT_DIR/.venv/bin/uvicorn" >&2
  echo "Create/install the venv first, for example: python3 -m pip install -e \"backend[dev]\"" >&2
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  echo "Frontend dependencies are missing: $FRONTEND_DIR/node_modules" >&2
  echo "Run npm install in $FRONTEND_DIR first." >&2
  exit 1
fi

cd "$ROOT_DIR"

if tmux has-session -t "$TMUX_SESSION" 2>/dev/null; then
  echo "tmux: stopping existing session '$TMUX_SESSION'."
  tmux kill-session -t "$TMUX_SESSION"
fi

stop_port "$BACKEND_PORT" "Backend"
for port in "$FRONTEND_PORT" 5173; do
  stop_port "$port" "Frontend"
done

BACKEND_LOG="$LOG_DIR/backend.out.log"
FRONTEND_LOG="$LOG_DIR/frontend.out.log"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

BACKEND_CMD="cd '$ROOT_DIR' && exec .venv/bin/uvicorn caseclosed.main:app --app-dir backend/src --env-file .env --host '$BACKEND_HOST' --port '$BACKEND_PORT' 2>&1 | tee -a '$BACKEND_LOG'"
FRONTEND_EXTRA_ARGS=""
if [[ "$NO_HTTPS" == "1" ]]; then
  FRONTEND_EXTRA_ARGS=" --https=false"
fi
FRONTEND_CMD="cd '$FRONTEND_DIR' && exec npm run dev -- --host '$FRONTEND_HOST' --port '$FRONTEND_PORT' --strictPort$FRONTEND_EXTRA_ARGS 2>&1 | tee -a '$FRONTEND_LOG'"

tmux new-session -d -s "$TMUX_SESSION" -n backend "$BACKEND_CMD"
tmux new-window -t "$TMUX_SESSION" -n frontend "$FRONTEND_CMD"

wait_http_ok "http://127.0.0.1:$BACKEND_PORT/health" "Backend"

FRONTEND_SCHEME="http"
if [[ "$NO_HTTPS" != "1" && -f "$ROOT_DIR/certs/caseclosed-dev.pfx" ]]; then
  FRONTEND_SCHEME="https"
fi
wait_http_ok "$FRONTEND_SCHEME://127.0.0.1:$FRONTEND_PORT/" "Frontend"

TAILSCALE_IP="$(ip -4 addr show tailscale0 2>/dev/null | sed -n 's/.*inet \([0-9.]\+\)\/.*/\1/p' | head -n 1 || true)"

echo
echo "CaseClosed dev servers restarted in tmux session '$TMUX_SESSION'."
echo "Backend URL : http://127.0.0.1:$BACKEND_PORT"
echo "Frontend URL: $FRONTEND_SCHEME://127.0.0.1:$FRONTEND_PORT/"
if [[ -n "$TAILSCALE_IP" ]]; then
  echo "Tailscale   : $FRONTEND_SCHEME://$TAILSCALE_IP:$FRONTEND_PORT/"
fi
echo "Logs        : $LOG_DIR"
echo
echo "Attach logs : tmux attach -t $TMUX_SESSION"
echo "Stop servers: tmux kill-session -t $TMUX_SESSION"
