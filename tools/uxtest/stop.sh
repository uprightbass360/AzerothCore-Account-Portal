#!/usr/bin/env bash
# Tear down the UX-test harness started by run.sh.
set -uo pipefail
UX="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$UX/.pids" ]; then
  while read -r name pid; do
    if kill "$pid" >/dev/null 2>&1; then echo "stopped $name ($pid)"; fi
    # vite/uvicorn spawn children; sweep the process group politely
    pkill -P "$pid" >/dev/null 2>&1 || true
  done < "$UX/.pids"
  rm -f "$UX/.pids"
fi
docker rm -f uxtest-mailhog >/dev/null 2>&1 && echo "stopped mailhog"
echo "done (seeded data kept in $UX/.data — delete it for a fresh slate)"
