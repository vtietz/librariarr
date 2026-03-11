#!/usr/bin/env bash
set -euo pipefail

run_as_configured_user() {
  local target_uid="$1"
  local target_gid="$2"
  shift 2
  local group_name="librariarr"
  local user_name="librariarr"
  local existing_group
  local existing_user

  existing_group="$(getent group "${target_gid}" | cut -d: -f1 || true)"
  if [[ -n "${existing_group}" ]]; then
    group_name="${existing_group}"
  else
    groupadd --gid "${target_gid}" "${group_name}"
  fi

  existing_user="$(getent passwd "${target_uid}" | cut -d: -f1 || true)"
  if [[ -n "${existing_user}" ]]; then
    user_name="${existing_user}"
    usermod --gid "${target_gid}" "${user_name}" >/dev/null 2>&1 || true
  else
    useradd --uid "${target_uid}" --gid "${target_gid}" --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin "${user_name}"
  fi

  exec gosu "${target_uid}:${target_gid}" python -m librariarr.main "$@"
}

if [[ "$(id -u)" -eq 0 ]]; then
  if [[ -n "${PUID:-}" && -n "${PGID:-}" ]]; then
    if [[ "${PUID}" =~ ^[0-9]+$ && "${PGID}" =~ ^[0-9]+$ ]]; then
      run_as_configured_user "${PUID}" "${PGID}" "$@"
    else
      echo "Warning: PUID/PGID must be numeric. Running as root." >&2
    fi
  fi
fi

exec python -m librariarr.main "$@"
