#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
DEV_COMPOSE_FILE="docker-compose.dev.yml"
E2E_COMPOSE_FILE="docker-compose.e2e.yml"
FS_E2E_COMPOSE_FILE="docker-compose.fs-e2e.yml"
PROJECT_NAME="librariarr"
SERVICE="librariarr"
DEV_SERVICE="librariarr-dev"
DEV_UI_SERVICE="librariarr-ui-dev"
DEV_RADARR_SERVICE="radarr-dev"
DEV_SONARR_SERVICE="sonarr-dev"
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
  e2e         Run end-to-end integration tests against live Arr services
  fs-e2e      Run end-to-end filesystem tests in Docker
  radarr-e2e  Alias for e2e
  sonarr-e2e  Alias for e2e
  quality     Run lint/format/complexity/LOC checks in Docker
  quality-autofix  Apply auto-fixes, then run quality checks
  dev-up      Start dev API, UI, Sonarr, and Radarr services
  dev-bootstrap  Configure dev Arr instances and sync API keys into config.yaml
  dev-seed    Create fake movie/series folders/files in configured source roots
  dev-down    Stop dev services
  dev-logs    Tail dev service logs
  dev-shell   Open shell in dev container
EOF
}

compose() {
  "${COMPOSE_CMD[@]}" -p "$PROJECT_NAME" -f "$COMPOSE_FILE" "$@"
}

compose_dev() {
  "${COMPOSE_CMD[@]}" -p "$PROJECT_NAME" -f "$DEV_COMPOSE_FILE" "$@"
}

compose_e2e() {
  "${COMPOSE_CMD[@]}" -p "$PROJECT_NAME" -f "$E2E_COMPOSE_FILE" "$@"
}

compose_fs_e2e() {
  "${COMPOSE_CMD[@]}" -p "$PROJECT_NAME" -f "$FS_E2E_COMPOSE_FILE" "$@"
}

cmd="${1:-}"

case "$cmd" in
  setup)
    if [[ -d config.yaml ]]; then
      if [[ -z "$(ls -A config.yaml)" ]]; then
        rmdir config.yaml
        cp config.yaml.example config.yaml
        echo "Replaced empty config.yaml directory with config file from config.yaml.example"
      else
        echo "Error: config.yaml is a directory with contents. Move/remove it, then run ./run.sh setup." >&2
        exit 1
      fi
    elif [[ ! -f config.yaml ]]; then
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
    if [[ "${LIBRARIARR_BUILD:-0}" == "1" ]]; then
      compose_dev build "$DEV_SERVICE"
    fi
    compose_dev run --rm "$DEV_SERVICE" \
      "LIBRARIARR_RADARR_URL= LIBRARIARR_RADARR_API_KEY= LIBRARIARR_SONARR_URL= LIBRARIARR_SONARR_API_KEY= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m 'not e2e and not fs_e2e and not radarr_e2e and not sonarr_e2e' -p no:cacheprovider ${LIBRARIARR_PYTEST_ARGS:-}"
    ;;
  e2e)
    mkdir -p .e2e-data/arr-e2e/movies .e2e-data/arr-e2e/radarr_library .e2e-data/arr-e2e/series .e2e-data/arr-e2e/sonarr_library
    compose_e2e down -v --remove-orphans >/dev/null 2>&1 || true
    compose_e2e run --rm "$E2E_SERVICE"
    ;;
  fs-e2e)
    mkdir -p .e2e-data
    compose_fs_e2e run --rm "$FS_E2E_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app pytest -q -m fs_e2e -p no:cacheprovider"
    ;;
  radarr-e2e)
    mkdir -p .e2e-data/arr-e2e/movies .e2e-data/arr-e2e/radarr_library .e2e-data/arr-e2e/series .e2e-data/arr-e2e/sonarr_library
    compose_e2e down -v --remove-orphans >/dev/null 2>&1 || true
    compose_e2e run --rm "$E2E_SERVICE"
    ;;
  sonarr-e2e)
    mkdir -p .e2e-data/arr-e2e/movies .e2e-data/arr-e2e/radarr_library .e2e-data/arr-e2e/series .e2e-data/arr-e2e/sonarr_library
    compose_e2e down -v --remove-orphans >/dev/null 2>&1 || true
    compose_e2e run --rm "$E2E_SERVICE"
    ;;
  quality)
    compose_dev run --rm "$DEV_SERVICE" \
      "LIBRARIARR_RADARR_URL= LIBRARIARR_RADARR_API_KEY= LIBRARIARR_SONARR_URL= LIBRARIARR_SONARR_API_KEY= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app bash ./tools/run_backend_quality.sh check"
    compose_dev run --rm "$DEV_UI_SERVICE" \
      "sh /app/tools/run_frontend_quality.sh check"
    ;;
  quality-autofix)
    compose_dev run --rm "$DEV_SERVICE" \
      "LIBRARIARR_RADARR_URL= LIBRARIARR_RADARR_API_KEY= LIBRARIARR_SONARR_URL= LIBRARIARR_SONARR_API_KEY= PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app bash ./tools/run_backend_quality.sh autofix"
    compose_dev run --rm "$DEV_UI_SERVICE" \
      "sh /app/tools/run_frontend_quality.sh autofix"
    ;;
  dev-up)
    "$0" setup
    if [[ ! -f .env && -f .env.dev.example ]]; then
      cp .env.dev.example .env
      echo "Created .env from .env.dev.example"
    fi
    bash ./tools/dev_prepare_media_layout.sh
    compose_dev up -d "$DEV_SERVICE" "$DEV_UI_SERVICE" "$DEV_RADARR_SERVICE" "$DEV_SONARR_SERVICE"
    if [[ "${LIBRARIARR_DEV_BOOTSTRAP:-1}" != "0" ]]; then
      "$0" dev-bootstrap
    fi
    web_port="${LIBRARIARR_WEB_PORT:-8787}"
    radarr_port="${DEV_HOST_PORT_RADARR:-17878}"
    sonarr_port="${DEV_HOST_PORT_SONARR:-18989}"
    echo ""
    echo "Dev services are up. Open:"
    echo "- LibrariArr admin GUI: http://localhost:${web_port}"
    echo "- Vite dev UI:           http://localhost:5173"
    echo "- Radarr admin:          http://localhost:${radarr_port}"
    echo "- Sonarr admin:          http://localhost:${sonarr_port}"
    ;;
  dev-bootstrap)
    "$0" setup
    compose_dev run --rm --user "0:0" "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app python -m librariarr.dev.media_permissions"
    compose_dev run --rm "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app python -m librariarr.dev.bootstrap"
    compose_dev restart "$DEV_SERVICE"
    ;;
  dev-seed)
    "$0" setup
    compose_dev run --rm --user "0:0" "$DEV_SERVICE" \
      "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app python -m librariarr.dev.seed && python -m librariarr.dev.media_permissions"
    ;;
  dev-down)
    compose_dev down
    ;;
  dev-logs)
    compose_dev logs -f "$DEV_SERVICE" "$DEV_UI_SERVICE" "$DEV_RADARR_SERVICE" "$DEV_SONARR_SERVICE"
    ;;
  dev-shell)
    compose_dev run --rm "$DEV_SERVICE" bash
    ;;
  *)
    usage
    exit 1
    ;;
esac
