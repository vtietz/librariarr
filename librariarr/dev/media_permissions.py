from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger("librariarr.dev.media_permissions")
CONFIG_PATH = Path("/config/config.yaml")

DEFAULT_MEDIA_PATHS: tuple[Path, ...] = (
    Path("/data/movies"),
    Path("/data/series"),
    Path("/data/radarr_library"),
    Path("/data/sonarr_library"),
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    return {}


def _extract_data_paths(
    mappings: Any,
    keys: tuple[str, ...],
) -> list[Path]:
    if not isinstance(mappings, list):
        return []
    paths: list[Path] = []
    for item in mappings:
        if not isinstance(item, dict):
            continue
        for key in keys:
            value = str(item.get(key, "")).strip()
            if value.startswith("/data/"):
                paths.append(Path(value))
    return paths


def _collect_media_paths(payload: dict[str, Any]) -> list[Path]:
    collected: list[Path] = list(DEFAULT_MEDIA_PATHS)
    paths_section = payload.get("paths", {})

    collected.extend(
        _extract_data_paths(
            paths_section.get("series_root_mappings", []),
            ("nested_root", "shadow_root"),
        )
    )
    collected.extend(
        _extract_data_paths(
            paths_section.get("movie_root_mappings", []),
            ("managed_root", "library_root"),
        )
    )

    ordered: list[Path] = []
    seen: set[str] = set()
    for candidate in collected:
        normalized = str(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(candidate)
    return ordered


def _read_numeric_env(name: str, default_value: int) -> int:
    raw = os.getenv(name, str(default_value)).strip()
    try:
        return int(raw)
    except ValueError:
        LOG.warning("Invalid %s=%r; using %s", name, raw, default_value)
        return default_value


def _ensure_and_chown(path: Path, uid: int, gid: int) -> tuple[bool, bool]:
    created = False
    chowned = False

    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        created = True

    os.chown(path, uid, gid)
    chowned = True
    return created, chowned


def _recursive_chown(root: Path, uid: int, gid: int) -> int:
    """Recursively chown all files and directories under *root*."""
    fixed = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            entry = Path(dirpath) / name
            try:
                stat = entry.lstat()
                if stat.st_uid != uid or stat.st_gid != gid:
                    os.lchown(entry, uid, gid)
                    fixed += 1
            except OSError:
                pass
    return fixed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    uid = _read_numeric_env("PUID", 1000)
    gid = _read_numeric_env("PGID", 1000)
    payload = _load_yaml(CONFIG_PATH)
    target_paths = _collect_media_paths(payload)

    created_count = 0
    chowned_count = 0
    fixed_count = 0

    for target_path in target_paths:
        try:
            created, chowned = _ensure_and_chown(target_path, uid, gid)
            if created:
                created_count += 1
            if chowned:
                chowned_count += 1
            fixed_count += _recursive_chown(target_path, uid, gid)
        except PermissionError:
            LOG.warning("Skipping %s due to permission constraints", target_path)
        except OSError as exc:
            LOG.warning("Skipping %s due to OS error: %s", target_path, exc)

    LOG.info(
        "Media permission repair completed "
        "(paths=%s created=%s chowned=%s fixed=%s uid=%s gid=%s)",
        len(target_paths),
        created_count,
        chowned_count,
        fixed_count,
        uid,
        gid,
    )


if __name__ == "__main__":
    main()
