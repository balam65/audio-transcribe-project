#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8000}"
NGROK_API="http://127.0.0.1:4040/api/tunnels"

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok is not installed. Install it first, then rerun this script."
  exit 1
fi

if ! curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "Backend is not reachable on http://127.0.0.1:${PORT}"
  echo "Start it first:"
  echo "  cd \"$PROJECT_ROOT/backend\" && python main.py"
  exit 1
fi

read_public_url() {
  curl -fsS "$NGROK_API" 2>/dev/null \
    | python3 -c 'import json,sys
try:
    data = json.load(sys.stdin)
except Exception:
    print("")
    raise SystemExit(0)
print(next((t.get("public_url", "") for t in data.get("tunnels", []) if t.get("proto") == "https"), ""))' \
    || true
}

existing_url="$(read_public_url)"

if [[ -n "$existing_url" ]]; then
  echo "Public link already active:"
  echo "$existing_url"
  exit 0
fi

log_file="$PROJECT_ROOT/.ngrok.log"
pid_file="$PROJECT_ROOT/.ngrok.pid"

nohup ngrok http "$PORT" >"$log_file" 2>&1 &
echo $! >"$pid_file"

for _ in $(seq 1 20); do
  public_url="$(read_public_url)"

  if [[ -n "$public_url" ]]; then
    echo "Public link ready:"
    echo "$public_url"
    exit 0
  fi

  sleep 1
done

echo "ngrok started, but no public URL was returned yet."
echo "Check logs at: $log_file"
exit 1
