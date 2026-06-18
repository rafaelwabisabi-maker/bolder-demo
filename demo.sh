#!/bin/bash
# One-command proof for this repo.
#
#   bash demo.sh
#
# Sets up the environment, runs the test suite, boots the API, hits the public
# /health endpoint, and demonstrates the governance layer that blocks an agent
# from running destructive commands — all in one shot. No secrets required:
# the tests stub the model, and /health needs no auth.
set -uo pipefail
cd "$(dirname "$0")"

say() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }
PORT="${PORT:-8099}"

say "1/4  Environment"
python3 -m venv .venv 2>/dev/null || true
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt -r requirements-dev.txt

say "2/4  Test suite — the quality gate (each test pins a real failure mode)"
python -m pytest -q || { echo "TESTS FAILED — stopping."; exit 1; }

say "3/4  Live /health (booting uvicorn on :$PORT)"
uvicorn main:app --host 127.0.0.1 --port "$PORT" >/tmp/bolder_demo_server.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT
# Poll until the server is ready (don't guess with a fixed sleep).
ready=""
for _ in $(seq 1 20); do
  sleep 1
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/health" 2>/dev/null)" = "200" ]; then ready=1; break; fi
done
if [ -n "$ready" ]; then
  echo -n "GET /health -> "; curl -s "http://127.0.0.1:$PORT/health"; echo
else
  echo "server did not become ready in 20s — see /tmp/bolder_demo_server.log"; exit 1
fi

say "4/4  Governance — destructive commands are blocked before they run"
bash governance/prove_guardian.sh

say "Done — tests, a live endpoint, and the safety layer, proven in one command."
