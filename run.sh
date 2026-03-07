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
  build       Build the production image
  up          Start service in background
  down        Stop and remove service containers
  restart     Restart service
  logs        Tail service logs
  once        Run one reconcile cycle and exit
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
