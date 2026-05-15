from __future__ import annotations

from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RuntimeConfig,
)
from librariarr.projection.models import MovieProjectionMapping
from librariarr.projection.planner import build_movie_projection_plans


def _make_config(tmp_path: Path) -> AppConfig:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        paths=PathsConfig(
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_root), library_root=str(library_root))
            ]
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="test-key"),
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(),
    )


def test_build_plans_rejects_conflicting_provenance_folder_fallback(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    managed_root = Path(config.paths.movie_root_mappings[0].managed_root)
    library_root = Path(config.paths.movie_root_mappings[0].library_root)

    wrong_stored = managed_root / "Der Unbeugsame (1967) FSK16"
    wrong_stored.mkdir(parents=True)
    (wrong_stored / "movie.mkv").write_text("x", encoding="utf-8")

    # Radarr path points to library (so direct managed path is unresolved),
    # but provenance fallback is for a different year and must not be used.
    movies = [
        {
            "id": 42,
            "title": "Der Unbeugsame",
            "year": 1984,
            "path": str(library_root / "Der Unbeugsame (1984)"),
        }
    ]
    mappings = [MovieProjectionMapping(managed_root=managed_root, library_root=library_root)]

    plans = build_movie_projection_plans(
        config=config,
        movies=movies,
        mappings=mappings,
        scoped_movie_ids=None,
        provenance_folders={42: wrong_stored},
    )

    assert len(plans) == 1
    assert plans[0].skip_reason == "managed_folder_missing"
    assert plans[0].managed_folder != wrong_stored
    assert plans[0].files == []
