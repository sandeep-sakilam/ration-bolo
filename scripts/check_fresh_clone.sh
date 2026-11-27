#!/usr/bin/env bash
# Acceptance check 1: on a fresh clone with no .env, `docker compose up` starts the
# app, the call simulator loads and the status banner lists missing keys as
# "key not set".
#
# Usage: scripts/check_fresh_clone.sh [repo-url | local-repo-dir] [branch]
# Env:   BUILD_ARGS  extra `docker build` arguments (e.g. proxy settings); optional
#        PORT        host port the compose file publishes (default 8000)
set -euo pipefail

REPO="${1:-https://github.com/sandeep-sakilam/ration-bolo}"
BRANCH="${2:-main}"
PORT="${PORT:-8000}"
PROJECT="rbfresh$$"
WORK="$(mktemp -d)"
cleanup() {
  (cd "$WORK/repo" 2>/dev/null && docker compose -p "$PROJECT" down -v >/dev/null 2>&1) || true
  rm -rf "$WORK"
}
trap cleanup EXIT

if [ -d "$REPO/.git" ]; then
  echo "==> Exporting committed files of $REPO (HEAD) as a fresh checkout"
  mkdir -p "$WORK/repo"
  git -C "$REPO" archive HEAD | tar -x -C "$WORK/repo"
  SHA="$(git -C "$REPO" rev-parse HEAD)"
else
  echo "==> Cloning $REPO ($BRANCH)"
  git clone --quiet --depth 1 --branch "$BRANCH" "$REPO" "$WORK/repo"
  SHA="$(git -C "$WORK/repo" rev-parse HEAD)"
fi
cd "$WORK/repo"
if [ -f .env ]; then echo "FAIL: a .env file is committed"; exit 1; fi

echo "==> Building the image"
# shellcheck disable=SC2086
DOCKER_BUILDKIT=1 docker build --quiet ${BUILD_ARGS:-} --build-arg GIT_SHA="$SHA" -t ration-bolo:local . >/dev/null

echo "==> docker compose up (no .env, no keys)"
docker compose -p "$PROJECT" up -d

echo "==> Waiting for /health"
for _ in $(seq 1 60); do
  if curl -fsS "http://localhost:$PORT/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "http://localhost:$PORT/health" >/dev/null || { echo "FAIL: app did not start";
  docker compose -p "$PROJECT" logs app | tail -40; exit 1; }

curl -fsS "http://localhost:$PORT/health" | grep -q "$SHA" \
  || { echo "FAIL: /health does not show build $SHA"; exit 1; }

page="$(curl -fsS "http://localhost:$PORT/simulator")"
echo "$page" | grep -qi "call simulator" || { echo "FAIL: simulator page missing"; exit 1; }
echo "$page" | grep -q "Demo data" || { echo "FAIL: demo data label missing"; exit 1; }

status="$(curl -fsS "http://localhost:$PORT/api/status")"
echo "$status" | grep -q "key not set" || { echo "FAIL: status does not say 'key not set'"; exit 1; }

reply="$(curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '{"caller":"lakshmi"}' "http://localhost:$PORT/api/sim/start")"
echo "$reply" | grep -q "0421" || { echo "FAIL: simulator call did not start"; exit 1; }

curl -fsS "http://localhost:$PORT/dealer" | grep -q "Dealer" || { echo "FAIL: dealer page missing"; exit 1; }
curl -fsS "http://localhost:$PORT/api/dealer/overview" | grep -q '"waiting"' \
  || { echo "FAIL: dealer dashboard needs a PIN (login wall)"; exit 1; }
curl -fsS "http://localhost:$PORT/api/admin/shops" | grep -q '"code"' \
  || { echo "FAIL: admin page needs a PIN (login wall)"; exit 1; }

echo "PASS: fresh clone starts with no .env and no keys; simulator loads; missing keys shown as 'key not set'; dealer and admin open with no PIN; /health shows build ${SHA:0:7}."
