#!/usr/bin/env bash
set -euo pipefail

mode="${1:-check}"

case "$mode" in
  check)
    ruff check . --no-cache
    ruff format --check . --no-cache
    ;;
  autofix)
    ruff check . --fix --no-cache
    ruff format . --no-cache
    ;;
  *)
    echo "Usage: bash ./tools/run_backend_quality.sh [check|autofix]" >&2
    exit 1
    ;;
esac

bash ./tools/check_max_lines.sh 700
bash ./tools/check_max_lines.sh 500 --extensions ts,tsx --label frontend-typescript ui/src ui/vite.config.ts
radon cc -s -n B librariarr tests
radon raw -s librariarr tests