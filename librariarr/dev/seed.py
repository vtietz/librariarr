from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

LOG = logging.getLogger("librariarr.dev.seed")
CONFIG_PATH = Path("/config/config.yaml")

SAMPLE_MOVIES: list[tuple[str, int]] = [
    ("Movie A", 2020),
    ("Movie B", 2021),
    ("Movie C", 2022),
]

SAMPLE_SERIES: list[tuple[str, int]] = [
    ("Series Alpha", 2021),
    ("Series Beta", 2022),
    ("Series Gamma", 2023),
]


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    return {}


def _extract_seed_targets(payload: dict[str, Any]) -> list[tuple[Path, str]]:
    mappings = payload.get("paths", {}).get("root_mappings", [])
    if not isinstance(mappings, list):
        return []

    roots: list[tuple[Path, str]] = []
    seen: dict[str, int] = {}

    for item in mappings:
        if not isinstance(item, dict):
            continue

        nested_root = str(item.get("nested_root", "")).strip()
        shadow_root = str(item.get("shadow_root", "")).strip().lower()
        if not nested_root:
            continue

        is_series_root = "sonarr" in shadow_root or "/series" in nested_root.lower()
        root_kind = "series" if is_series_root else "movies"

        if nested_root in seen:
            existing_index = seen[nested_root]
            existing_kind = roots[existing_index][1]
            if existing_kind != "series" and root_kind == "series":
                roots[existing_index] = (Path(nested_root), root_kind)
            continue

        seen[nested_root] = len(roots)
        roots.append((Path(nested_root), root_kind))

    return roots


def _movie_file_name(title: str, year: int) -> str:
    return f"{title.replace(' ', '.')}.{year}.1080p.mkv"


def _seed_movie_root(root: Path) -> tuple[int, int]:
    created_dirs = 0
    created_files = 0

    for title, year in SAMPLE_MOVIES:
        movie_dir = root / f"{title} ({year})"
        if not movie_dir.exists():
            movie_dir.mkdir(parents=True, exist_ok=True)
            created_dirs += 1

        movie_file = movie_dir / _movie_file_name(title, year)
        if not movie_file.exists():
            movie_file.write_bytes(b"x" * 2048)
            created_files += 1

    return created_dirs, created_files


def _episode_file_name(title: str, year: int, season: int, episode: int) -> str:
    safe_title = title.replace(" ", ".")
    return f"{safe_title}.{year}.S{season:02d}E{episode:02d}.1080p.mkv"


def _seed_series_root(root: Path) -> tuple[int, int]:
    created_dirs = 0
    created_files = 0

    for title, year in SAMPLE_SERIES:
        series_dir = root / f"{title} ({year})"
        if not series_dir.exists():
            series_dir.mkdir(parents=True, exist_ok=True)
            created_dirs += 1

        season_dir = series_dir / "Season 01"
        if not season_dir.exists():
            season_dir.mkdir(parents=True, exist_ok=True)
            created_dirs += 1

        for episode in (1, 2):
            episode_file = season_dir / _episode_file_name(title, year, season=1, episode=episode)
            if not episode_file.exists():
                episode_file.write_bytes(b"x" * 2048)
                created_files += 1

    return created_dirs, created_files


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    payload = _load_yaml(CONFIG_PATH)
    seed_targets = _extract_seed_targets(payload)
    if not seed_targets:
        LOG.warning("No nested_root entries found in %s; nothing to seed", CONFIG_PATH)
        return

    total_dirs = 0
    total_files = 0

    for nested_root, root_kind in seed_targets:
        try:
            nested_root.mkdir(parents=True, exist_ok=True)
            if root_kind == "series":
                created_dirs, created_files = _seed_series_root(nested_root)
            else:
                created_dirs, created_files = _seed_movie_root(nested_root)
            total_dirs += created_dirs
            total_files += created_files
            LOG.info(
                "Seeded %s [%s] (created_dirs=%s created_files=%s)",
                nested_root,
                root_kind,
                created_dirs,
                created_files,
            )
        except PermissionError:
            LOG.warning("Skipping seed for %s due to permission constraints", nested_root)

    LOG.info("Dev seed completed (created_dirs=%s created_files=%s)", total_dirs, total_files)


if __name__ == "__main__":
    main()
