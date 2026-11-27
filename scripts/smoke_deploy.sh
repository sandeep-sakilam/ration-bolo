#!/usr/bin/env bash
# Smoke-test a deployed Ration Bolo (Railway or a tunnel). Reads only; changes nothing
# except starting one simulator session.
# Usage: scripts/smoke_deploy.sh https://your-app.up.railway.app
set -euo pipefail
BASE="${1:?usage: smoke_deploy.sh BASE_URL}"
BASE="${BASE%/}"

curl -fsS "$BASE/health" | grep -q '"ok"' && echo "ok   /health"
curl -fsS "$BASE/simulator" | grep -qi "call simulator" && echo "ok   /simulator"
status="$(curl -fsS "$BASE/api/status")"
echo "ok   /api/status"
python3 - "$status" <<'PY'
import json, sys
s = json.loads(sys.argv[1])
for svc in s["services"]:
    print(f"     {svc['provider']:<28} {svc['note']}")
for name, ch in s["channels"].items():
    print(f"     channel {name:<19} {'ready' if ch['ready'] else ch['note']}")
PY
curl -fsS -X POST -H 'Content-Type: application/json' -d '{"caller":"lakshmi"}' \
  "$BASE/api/sim/start" | grep -q 0421 && echo "ok   simulator call"
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/twilio/voice" -d 'From=%2B10000000000')"
echo "     unsigned /twilio/voice → HTTP $code (403 expected once Twilio keys are set)"
