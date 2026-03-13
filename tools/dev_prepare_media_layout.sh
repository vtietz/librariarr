#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

read_env_value() {
  local key="$1"
  local env_file="$2"
  local line=""

  if [[ ! -f "$env_file" ]]; then
    return 1
  fi

  while IFS= read -r candidate; do
    [[ "$candidate" =~ ^[[:space:]]*# ]] && continue
    if [[ "$candidate" == "$key="* ]]; then
      line="$candidate"
    fi
  done < "$env_file"

  if [[ -z "$line" ]]; then
    return 1
  fi

  printf '%s' "${line#*=}"
}

resolve_media_root() {
  local media_root="${MEDIA_ROOT:-}"

  if [[ -z "$media_root" ]]; then
    media_root="$(read_env_value "MEDIA_ROOT" "$ENV_FILE" || true)"
  fi
  if [[ -z "$media_root" ]]; then
    media_root="./data/dev-media"
  fi

  printf '%s' "$media_root"
}

main() {
  local media_root
  local host_media_root
  local parent_dir

  media_root="$(resolve_media_root)"
  host_media_root="$media_root"

  if [[ "$host_media_root" != /* ]]; then
    host_media_root="$REPO_ROOT/${host_media_root#./}"
  fi

  if [[ -d "$host_media_root" ]]; then
    if [[ ! -w "$host_media_root" ]]; then
      echo "Info: host pre-create skipped for $host_media_root; in-container repair will run during dev-bootstrap" >&2
      return 0
    fi
  else
    parent_dir="$(dirname "$host_media_root")"
    if [[ ! -d "$parent_dir" || ! -w "$parent_dir" ]]; then
      echo "Info: host pre-create skipped for $host_media_root; in-container repair will run during dev-bootstrap" >&2
      return 0
    fi
  fi

  if mkdir -p \
    "$host_media_root/movies" \
    "$host_media_root/series" \
    "$host_media_root/radarr_library" \
    "$host_media_root/sonarr_library"; then
    echo "Ensured dev media directories under $host_media_root"
  else
    echo "Info: host pre-create skipped for $host_media_root; in-container repair will run during dev-bootstrap" >&2
  fi
}

main "$@"
