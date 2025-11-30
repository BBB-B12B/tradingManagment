#!/usr/bin/env bash
# Kill any existing dev worker on PORT (default 8787) then start wrangler dev.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PORT="${PORT:-8787}"

echo ">> Ensuring port ${PORT} is free..."
PORT="${PORT}" "${SCRIPT_DIR}/kill-port-8787.sh"

echo ">> Starting wrangler dev on port ${PORT} (service: cloudflare_api)"
cd "${ROOT_DIR}/services/cloudflare_api"
exec wrangler dev --port "${PORT}"
