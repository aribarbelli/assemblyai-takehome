#!/usr/bin/env bash
# Starts the local LiveKit server, the agent, and the web UI. Ctrl+C stops all three.
set -euo pipefail
cd "$(dirname "$0")"
source .venv/bin/activate

trap 'kill 0' EXIT

livekit-server --dev --bind 127.0.0.1 > livekit-server.log 2>&1 &
sleep 1
python agent.py dev &
python server.py &

wait
