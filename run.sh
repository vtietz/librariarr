#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
SERVICE="librariarr"
DEV_SERVICE="librariarr-dev"

usage() {
  cat <<'EOF'
Usage: ./run.sh <command>

Commands:
  setup       Create config.yaml from example if missing
  install     Build dev image with dependencies (cached)
  build       Build the production image
  up          Start service in background
  down        Stop and remove service containers
  restart     Restart service
  logs        Tail service logs
  once        Run one reconcile cycle and exit
  test        Run unit tests in Docker
  e2e         Run end-to-end filesystem tests in Docker
  quality     Run lint/format/complexity/LOC checks in Docker
  quality-autofix  Apply auto-fixes, then run quality checks
  dev-up      Start dev profile service in background
  dev-down    Stop dev profile service
  dev-logs    Tail dev profile logs
  dev-shell   Open shell in dev container
EOF
}

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

cmd="${1:-}"

case "$cmd" in
  setup)
    if [[ ! -f config.yaml ]]; then
      cp config.yaml.example config.yaml
      echo "Created config.yaml from config.yaml.example"
    else
      echo "config.yaml already exists"
    fi
    ;;
  install)
    compose --profile dev build "$DEV_SERVICE"
    ;;
  build)
    compose build "$SERVICE"
    ;;
  up)
    compose up -d "$SERVICE"
    ;;
  down)
    compose down
    ;;
  restart)
    compose restart "$SERVICE"
    ;;
  logs)
    compose logs -f "$SERVICE"
    ;;
  once)
    compose run --rm "$SERVICE" --config /config/config.yaml --once
    ;;
  test)
    compose --profile dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m 'not e2e' -p no:cacheprovider"
    ;;
  e2e)
    mkdir -p .e2e-data
    compose --profile e2e run --rm "librariarr-e2e" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m e2e -p no:cacheprovider"
    ;;
  quality)
    compose --profile dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app ruff check . --no-cache && \
       PYTHONPATH=/app ruff format --check . --no-cache && \
       radon cc -s -n B librariarr tests && \
       radon raw -s librariarr tests"
    ;;
  quality-autofix)
    compose --profile dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app ruff check . --fix --no-cache && \
       PYTHONPATH=/app ruff format . --no-cache && \
       radon cc -s -n B librariarr tests && \
       radon raw -s librariarr tests"
    ;;
  dev-up)
    compose --profile dev up -d "$DEV_SERVICE"
    ;;
  dev-down)
    compose --profile dev down
    ;;
  dev-logs)
    compose --profile dev logs -f "$DEV_SERVICE"
    ;;
  dev-shell)
    compose --profile dev run --rm "$DEV_SERVICE" bash
    ;;
  *)
    usage
    exit 1
    ;;
esac
