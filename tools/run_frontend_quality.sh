#!/bin/sh
set -eu

mode="${1:-check}"

NPM_CONFIG_PRODUCTION=false NODE_ENV=development npm install --include=dev --no-audit --no-fund

case "$mode" in
  check)
    npm run quality
    ;;
  autofix)
    npm run quality:autofix
    ;;
  *)
    echo "Usage: sh /app/tools/run_frontend_quality.sh [check|autofix]" >&2
    exit 1
    ;;
esac