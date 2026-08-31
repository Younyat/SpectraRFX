#!/usr/bin/env bash
# Start Spectrum Lab backend and frontend in development mode.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
APP_SYNC_INTERVAL_MS="${APP_SYNC_INTERVAL_MS:-5000}"
SPECTRUM_POLL_INTERVAL_MS="${SPECTRUM_POLL_INTERVAL_MS:-100}"
WATERFALL_POLL_INTERVAL_MS="${WATERFALL_POLL_INTERVAL_MS:-100}"
INSTALL_DEPS="${INSTALL_DEPS:-1}"
INSTALL_TOOLS="${INSTALL_TOOLS:-1}"

log() {
  printf "\n==> %s\n" "$1"
}

find_python() {
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo "Python not found. Install Python 3.10+." >&2
    exit 1
  fi
}

install_node_with_apt() {
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi

  log "Installing Node.js and npm with apt-get"
  if command -v sudo >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y nodejs npm
  else
    apt-get update
    apt-get install -y nodejs npm
  fi
}

ensure_node() {
  if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
    return 0
  fi

  if [ "$INSTALL_TOOLS" != "1" ]; then
    echo "Node.js/npm not found. Install Node.js 18+ and npm, or run with INSTALL_TOOLS=1." >&2
    exit 1
  fi

  install_node_with_apt || {
    echo "Node.js/npm not found and automatic installation is not supported on this system." >&2
    echo "Install Node.js 18+ manually, then rerun: bash scripts/run_dev.sh" >&2
    exit 1
  }

  command -v node >/dev/null 2>&1 || {
    echo "Node.js installation finished, but 'node' is still not available in PATH." >&2
    exit 1
  }
  command -v npm >/dev/null 2>&1 || {
    echo "npm installation finished, but 'npm' is still not available in PATH." >&2
    exit 1
  }
}

venv_python() {
  if [ -x "$BACKEND_DIR/venv/bin/python" ]; then
    echo "$BACKEND_DIR/venv/bin/python"
  elif [ -x "$BACKEND_DIR/venv/Scripts/python.exe" ]; then
    echo "$BACKEND_DIR/venv/Scripts/python.exe"
  else
    echo ""
  fi
}

cleanup() {
  log "Stopping services..."
  if [ -n "${BACKEND_PID:-}" ]; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [ -n "${FRONTEND_PID:-}" ]; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
}

trap cleanup EXIT INT TERM

log "Checking tools"
PYTHON_BIN="$(find_python)"
ensure_node

log "Preparing backend"
if [ ! -d "$BACKEND_DIR/venv" ]; then
  "$PYTHON_BIN" -m venv "$BACKEND_DIR/venv"
fi

VENV_PYTHON="$(venv_python)"
if [ -z "$VENV_PYTHON" ]; then
  echo "Virtual environment was created, but its Python binary was not found." >&2
  exit 1
fi

if [ "$INSTALL_DEPS" = "1" ]; then
  "$VENV_PYTHON" -m pip install --upgrade pip wheel "setuptools<82"
  "$VENV_PYTHON" -m pip install -r "$BACKEND_DIR/requirements.txt"
fi

log "Preparing frontend"
if [ "$INSTALL_DEPS" = "1" ] && [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  (cd "$FRONTEND_DIR" && npm install)
fi

log "Starting backend on http://localhost:$BACKEND_PORT"
(cd "$BACKEND_DIR" && "$VENV_PYTHON" -m uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT") &
BACKEND_PID=$!

log "Starting frontend on http://localhost:5173"
(cd "$FRONTEND_DIR" && VITE_APP_SYNC_INTERVAL_MS="$APP_SYNC_INTERVAL_MS" VITE_SPECTRUM_POLL_INTERVAL_MS="$SPECTRUM_POLL_INTERVAL_MS" VITE_WATERFALL_POLL_INTERVAL_MS="$WATERFALL_POLL_INTERVAL_MS" npm run dev -- --host "$FRONTEND_HOST") &
FRONTEND_PID=$!

printf "\nBackend API: http://localhost:%s\n" "$BACKEND_PORT"
printf "API docs:    http://localhost:%s/docs\n" "$BACKEND_PORT"
printf "Frontend:    http://localhost:5173\n"
printf "App sync interval:       %sms\n" "$APP_SYNC_INTERVAL_MS"
printf "Spectrum poll interval:  %sms\n" "$SPECTRUM_POLL_INTERVAL_MS"
printf "Waterfall poll interval: %sms\n" "$WATERFALL_POLL_INTERVAL_MS"
printf "\nPress Ctrl+C to stop both services.\n"

wait "$BACKEND_PID" "$FRONTEND_PID"
