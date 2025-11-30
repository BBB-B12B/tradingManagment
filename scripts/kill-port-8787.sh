#!/usr/bin/env bash
# Kill any process listening on port 8787 (used by wrangler dev in this repo).
set -euo pipefail

PORT="${PORT:-8787}"

pids=$(lsof -ti :"${PORT}" || true)
if [ -z "${pids}" ]; then
  echo "No process found on port ${PORT}"
  exit 0
fi

echo "Killing processes on port ${PORT}: ${pids}"
kill -9 ${pids}
echo "Done."
