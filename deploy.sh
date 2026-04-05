#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
git pull --ff-only origin autostopCRM
docker compose up -d --build
