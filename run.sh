#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
DEV_COMPOSE_FILE="docker-compose.dev.yml"
E2E_COMPOSE_FILE="docker-compose.e2e.yml"
FS_E2E_COMPOSE_FILE="docker-compose.fs-e2e.yml"
SERVICE="librariarr"
DEV_SERVICE="librariarr-dev"
E2E_SERVICE="librariarr-radarr-e2e"
FS_E2E_SERVICE="librariarr-e2e"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "Error: neither 'docker compose' nor 'docker-compose' is available." >&2
  exit 1
fi

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
  e2e         Run end-to-end integration tests against live Radarr
  fs-e2e      Run end-to-end filesystem tests in Docker
  radarr-e2e  Alias for e2e
  quality     Run lint/format/complexity/LOC checks in Docker
  quality-autofix  Apply auto-fixes, then run quality checks
  dev-up      Start dev profile service in background
  dev-down    Stop dev profile service
  dev-logs    Tail dev profile logs
  dev-shell   Open shell in dev container
EOF
}

compose() {
  "${COMPOSE_CMD[@]}" -f "$COMPOSE_FILE" "$@"
}

compose_dev() {
  "${COMPOSE_CMD[@]}" -f "$DEV_COMPOSE_FILE" "$@"
}

compose_e2e() {
  "${COMPOSE_CMD[@]}" -f "$E2E_COMPOSE_FILE" "$@"
}

compose_fs_e2e() {
  "${COMPOSE_CMD[@]}" -f "$FS_E2E_COMPOSE_FILE" "$@"
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
    compose_dev build "$DEV_SERVICE"
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
    compose_dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m 'not e2e and not fs_e2e and not radarr_e2e' -p no:cacheprovider"
    ;;
  e2e)
    mkdir -p .e2e-data/radarr-e2e/movies .e2e-data/radarr-e2e/radarr_library
    compose_e2e down -v --remove-orphans >/dev/null 2>&1 || true
    compose_e2e run --rm "$E2E_SERVICE"
    ;;
  fs-e2e)
    mkdir -p .e2e-data
    compose_fs_e2e run --rm "$FS_E2E_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m fs_e2e -p no:cacheprovider"
    ;;
  radarr-e2e)
    mkdir -p .e2e-data/radarr-e2e/movies .e2e-data/radarr-e2e/radarr_library
    compose_e2e down -v --remove-orphans >/dev/null 2>&1 || true
    compose_e2e run --rm "$E2E_SERVICE"
    ;;
  quality)
    compose_dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app ruff check . --no-cache && \
       PYTHONPATH=/app ruff format --check . --no-cache && \
       radon cc -s -n B librariarr tests && \
       radon raw -s librariarr tests"
    ;;
  quality-autofix)
    compose_dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app ruff check . --fix --no-cache && \
       PYTHONPATH=/app ruff format . --no-cache && \
       radon cc -s -n B librariarr tests && \
       radon raw -s librariarr tests"
    ;;
  dev-up)
    compose_dev up -d "$DEV_SERVICE"
    ;;
  dev-down)
    compose_dev down
    ;;
  dev-logs)
    compose_dev logs -f "$DEV_SERVICE"
    ;;
  dev-shell)
    compose_dev run --rm "$DEV_SERVICE" bash
    ;;
  *)
    usage
    exit 1
    ;;
esac
