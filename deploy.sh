#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if git ls-remote --exit-code origin autostopCRM >/dev/null 2>&1; then
  git fetch origin autostopCRM
  git reset --hard origin/autostopCRM
else
  echo "WARN: git origin is not reachable from this server; skipping git pull and rebuilding current working tree." >&2
fi
docker compose up -d --build
