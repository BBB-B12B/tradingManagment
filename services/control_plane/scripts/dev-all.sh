#!/usr/bin/env bash
set -euo pipefail

# One-command dev runner:
# 1) Start the Cloudflare worker locally
# 2) Wait until it responds
# 3) Start the control-plane (uvicorn) pointing to that worker

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
WORKER_DIR="$ROOT/services/cloudflare_api"
API_DIR="$ROOT/services/control_plane"

WORKER_PORT="${WORKER_PORT:-8787}"
WORKER_URL="${WORKER_URL:-http://127.0.0.1:${WORKER_PORT}}"
UVICORN_PORT="${UVICORN_PORT:-5001}"
WRANGLER_DEV_FLAGS="${WRANGLER_DEV_FLAGS:---remote}"

echo "ROOT:          $ROOT"
echo "WORKER_DIR:    $WORKER_DIR"
echo "API_DIR:       $API_DIR"
echo "WORKER_PORT:   $WORKER_PORT"
echo "WORKER_URL:    $WORKER_URL"
echo "UVICORN_PORT:  $UVICORN_PORT"
echo "WRANGLER_DEV_FLAGS: $WRANGLER_DEV_FLAGS"

# === CLEANUP OLD PROCESSES FIRST ===
echo "Cleaning up old processes..."
# Kill old Wrangler processes
pkill -f "wrangler dev" 2>/dev/null || true
# Kill old esbuild processes
pkill -f "esbuild --service" 2>/dev/null || true
# Kill old workerd processes
pkill -f "workerd serve" 2>/dev/null || true
# Kill old uvicorn processes on port 5001
lsof -ti:5001 | xargs kill -9 2>/dev/null || true
# Wait for cleanup
sleep 2
echo "Old processes cleaned up."

worker_pid=""
cleanup() {
  echo "Cleanup triggered..."
  if [[ -n "$worker_pid" ]] && kill -0 "$worker_pid" 2>/dev/null; then
    echo "Stopping worker (pid=$worker_pid)..."
    kill "$worker_pid" 2>/dev/null || true
  fi
  # Kill all wrangler/esbuild processes on exit
  pkill -f "wrangler dev" 2>/dev/null || true
  pkill -f "esbuild --service" 2>/dev/null || true
  pkill -f "workerd serve" 2>/dev/null || true
  echo "Cleanup complete."
}
trap cleanup EXIT INT TERM

echo "Starting worker with wrangler dev..."
export WRANGLER_LOG_DIR="${WRANGLER_LOG_DIR:-/tmp/wrangler-logs}"
mkdir -p "$WRANGLER_LOG_DIR"
# Disable inspector port to avoid EPERM on some systems
export MINIFLARE_INSPECTOR_PORT=0
(
  cd "$WORKER_DIR"
  PORT="$WORKER_PORT" wrangler dev $WRANGLER_DEV_FLAGS --port "$WORKER_PORT"
) &
worker_pid=$!
echo "Worker pid: $worker_pid"

echo "Waiting for worker to be ready..."
for i in {1..60}; do
  if curl -sSf "$WORKER_URL/orders" >/dev/null 2>&1; then
    echo "Worker is ready."
    break
  fi
  sleep 1
  if ! kill -0 "$worker_pid" 2>/dev/null; then
    echo "Worker process exited unexpectedly."
    exit 1
  fi
  if [[ $i -eq 60 ]]; then
    echo "Worker not responding after 60 seconds."
    exit 1
  fi
done

echo "Starting control plane (uvicorn)..."
cd "$API_DIR"
CDC_WORKER_URL="$WORKER_URL" CLOUDFLARE_WORKER_URL="$WORKER_URL" uvicorn src.app:app --reload --port "$UVICORN_PORT"
