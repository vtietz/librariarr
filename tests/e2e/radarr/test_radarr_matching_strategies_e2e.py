import os
import uuid
from pathlib import Path

import pytest

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RadarrProjectionConfig,
    RuntimeConfig,
)
from librariarr.projection import get_radarr_webhook_queue
from librariarr.service import LibrariArrService
from librariarr.sync.naming import safe_path_component
from tests.e2e.radarr.test_radarr_e2e import (
    _ensure_movie_path_under_managed_root,
    _resolve_case_root,
    _seed_movie_or_skip,
    _seed_slash_title_movie_or_skip,
    _wait_for_api_key,
    _wait_for_radarr,
)


def _projection_config(
    *,
    managed_root: Path,
    library_root: Path,
    radarr_url: str,
    api_key: str,
    sync_enabled: bool = False,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(managed_root),
                    library_root=str(library_root),
                )
            ],
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=sync_enabled,
            projection=RadarrProjectionConfig(),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )


@pytest.mark.e2e
def test_radarr_e2e_projection_uses_radarr_title_year_naming() -> None:
    case_root = _resolve_case_root(f"radarr_projection_managed_name_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Managed Name",
        title_slug="fixture-projection-managed-name-2020",
        tmdb_id=502356,
        year=2020,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "managed-name",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.Managed.Name.2020.1080p.x265.mkv"
    source_file.write_text("stub", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    title = str(seeded_movie.get("title") or "")
    year = seeded_movie.get("year")
    expected_folder = safe_path_component(f"{title} ({year})" if isinstance(year, int) else title)
    projected_file = library_root / expected_folder / source_file.name
    assert projected_file.exists()
    assert projected_file.samefile(source_file)


@pytest.mark.e2e
def test_radarr_e2e_projection_can_use_radarr_title_year_folder_naming() -> None:
    case_root = _resolve_case_root(f"radarr_projection_radarr_name_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    seeded_movie = _seed_slash_title_movie_or_skip(session, radarr_url, managed_root)
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "radarr-name",
    )
    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.Radarr.Name.1080p.x265.mkv"
    source_file.write_text("stub", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    title = str(seeded_movie.get("title") or "")
    year = seeded_movie.get("year")
    if isinstance(year, int):
        expected_folder_name = safe_path_component(f"{title} ({year})")
    else:
        expected_folder_name = safe_path_component(title)

    projected_file = library_root / expected_folder_name / source_file.name
    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert "/" not in expected_folder_name


@pytest.mark.e2e
def test_radarr_e2e_projection_scopes_to_webhook_movie_ids() -> None:
    case_root = _resolve_case_root(f"radarr_projection_scoped_webhook_{uuid.uuid4().hex[:8]}")

    managed_root = case_root / "managed_movies"
    library_root = case_root / "library_movies"
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    movie_a = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Scoped A",
        title_slug="fixture-projection-scoped-a-2018",
        tmdb_id=338970,
        year=2018,
    )
    movie_b = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Scoped B",
        title_slug="fixture-projection-scoped-b-2019",
        tmdb_id=502356,
        year=2019,
    )
    movie_a = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_a,
        managed_root,
        "scoped-a",
    )
    movie_b = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_b,
        managed_root,
        "scoped-b",
    )

    folder_a = Path(str(movie_a["path"]))
    folder_b = Path(str(movie_b["path"]))
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_a = folder_a / "Fixture.Projection.Scoped.A.2018.1080p.x265.mkv"
    source_b = folder_b / "Fixture.Projection.Scoped.B.2019.1080p.x265.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )

    queue = get_radarr_webhook_queue()
    queue.consume_movie_ids()
    try:
        queue.enqueue(
            movie_id=int(movie_b["id"]),
            event_type="MovieFileDelete",
            normalized_path=str(folder_b),
        )
        service.reconcile()
    finally:
        queue.consume_movie_ids()

    def _canon(m: dict) -> str:
        t = str(m.get("title") or "")
        y = m.get("year")
        return safe_path_component(f"{t} ({y})" if isinstance(y, int) else t)

    expected_a = _canon(movie_a)
    expected_b = _canon(movie_b)
    projected_a = library_root / expected_a / source_a.name
    projected_b = library_root / expected_b / source_b.name
    assert not projected_a.exists()
    assert projected_b.exists()
    assert projected_b.samefile(source_b)
