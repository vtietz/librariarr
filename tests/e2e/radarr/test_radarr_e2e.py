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
from tests.e2e.radarr.radarr_e2e_helpers import (
    canonical_name_from_seeded_movie,
    ensure_movie_path_under_managed_root,
    projection_config,
    resolve_case_root,
    seed_movie_or_skip,
    seed_slash_title_movie_or_skip,
    wait_for_api_key,
    wait_for_radarr,
)

# Backward-compatible aliases for other e2e test files that import these.
_resolve_case_root = resolve_case_root
_wait_for_api_key = wait_for_api_key
_wait_for_radarr = wait_for_radarr
_seed_movie_or_skip = seed_movie_or_skip
_seed_slash_title_movie_or_skip = seed_slash_title_movie_or_skip
_ensure_movie_path_under_managed_root = ensure_movie_path_under_managed_root
_canonical_name_from_seeded_movie = canonical_name_from_seeded_movie
_projection_config = projection_config


@pytest.mark.e2e
def test_radarr_e2e_reconcile_sanitizes_slash_title_paths() -> None:
    case_root = _resolve_case_root(f"radarr_projection_slash_title_{uuid.uuid4().hex[:8]}")

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
        "slash-title",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Slash.Title.Projection.1080p.x265.mkv"
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
    expected_folder_name = (
        safe_path_component(f"{title} ({year})")
        if isinstance(year, int)
        else safe_path_component(title)
    )
    projected_file = library_root / expected_folder_name / source_file.name

    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert "/" not in expected_folder_name


@pytest.mark.e2e
def test_radarr_e2e_reconcile_corrects_path_after_nfo_fix() -> None:
    case_root = _resolve_case_root(f"radarr_projection_relink_replace_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Projection Relink",
        title_slug="fixture-projection-relink-2014",
        tmdb_id=266856,
        year=2014,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "relink",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.Relink.2014.1080p.x265.mkv"
    source_file.write_text("v1", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    projected_file = library_root / managed_folder.relative_to(managed_root) / source_file.name
    assert projected_file.exists()
    assert projected_file.samefile(source_file)

    old_inode = projected_file.stat().st_ino
    source_file.unlink()
    source_file.write_text("v2", encoding="utf-8")

    service.reconcile()

    assert projected_file.exists()
    assert projected_file.samefile(source_file)
    assert projected_file.read_text(encoding="utf-8") == "v2"
    assert projected_file.stat().st_ino != old_inode


@pytest.mark.e2e
def test_radarr_e2e_reconcile_updates_existing_movie_path() -> None:
    case_root = _resolve_case_root(f"radarr_projection_no_path_mutation_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Projection No Path Mutation",
        title_slug="fixture-projection-no-path-mutation-2018",
        tmdb_id=338970,
        year=2018,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "no-path-mutation",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    baseline_path = str(seeded_movie.get("path") or "")
    managed_folder.mkdir(parents=True, exist_ok=True)
    source_file = managed_folder / "Fixture.Projection.No.Path.Mutation.2018.1080p.x265.mkv"
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

    projected_file = library_root / managed_folder.relative_to(managed_root) / source_file.name
    assert projected_file.exists()
    assert projected_file.samefile(source_file)

    movie_id = int(seeded_movie["id"])
    movie_resp = session.get(f"{radarr_url}/api/v3/movie/{movie_id}", timeout=20)
    movie_resp.raise_for_status()
    assert str(movie_resp.json().get("path") or "") == baseline_path


@pytest.mark.e2e
def test_radarr_e2e_projection_allowlisted_extras() -> None:
    case_root = _resolve_case_root(f"radarr_projection_allowlisted_extras_{uuid.uuid4().hex[:8]}")

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
        title="Fixture Projection Allowlisted Extras",
        title_slug="fixture-projection-allowlisted-extras-2022",
        tmdb_id=634649,
        year=2022,
    )
    seeded_movie = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        seeded_movie,
        managed_root,
        "allowlisted-extras",
    )

    managed_folder = Path(str(seeded_movie["path"]))
    managed_folder.mkdir(parents=True, exist_ok=True)
    video_file = managed_folder / "Fixture.Projection.Allowlisted.Extras.2022.1080p.x265.mkv"
    nfo_file = managed_folder / "movie.nfo"
    poster_file = managed_folder / "poster.jpg"
    ignored_file = managed_folder / "notes.txt"
    video_file.write_text("video", encoding="utf-8")
    nfo_file.write_text("<movie></movie>", encoding="utf-8")
    poster_file.write_text("poster", encoding="utf-8")
    ignored_file.write_text("ignore", encoding="utf-8")

    service = LibrariArrService(
        _projection_config(
            managed_root=managed_root,
            library_root=library_root,
            radarr_url=radarr_url,
            api_key=api_key,
        )
    )
    service.reconcile()

    projected_folder = library_root / managed_folder.relative_to(managed_root)
    projected_video = projected_folder / video_file.name
    projected_nfo = projected_folder / nfo_file.name
    projected_poster = projected_folder / poster_file.name
    projected_ignored = projected_folder / ignored_file.name

    assert projected_video.exists()
    assert projected_video.samefile(video_file)
    assert projected_nfo.exists()
    assert projected_nfo.samefile(nfo_file)
    assert projected_poster.exists()
    assert projected_poster.samefile(poster_file)
    assert not projected_ignored.exists()


@pytest.mark.e2e
def test_radarr_e2e_projection_scoped_webhook_reconcile() -> None:
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
        title="Fixture Projection Scoped Queue A",
        title_slug="fixture-projection-scoped-queue-a-2011",
        tmdb_id=11778,
        year=2011,
    )
    movie_b = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_root,
        title="Fixture Projection Scoped Queue B",
        title_slug="fixture-projection-scoped-queue-b-2012",
        tmdb_id=82702,
        year=2012,
    )

    movie_a = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_a,
        managed_root,
        "queue-a",
    )
    movie_b = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_b,
        managed_root,
        "queue-b",
    )

    folder_a = Path(str(movie_a["path"]))
    folder_b = Path(str(movie_b["path"]))
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_a = folder_a / "Fixture.Projection.Scoped.Queue.A.2011.1080p.x265.mkv"
    source_b = folder_b / "Fixture.Projection.Scoped.Queue.B.2012.1080p.x265.mkv"
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

    projected_a = library_root / folder_a.relative_to(managed_root) / source_a.name
    projected_b = library_root / folder_b.relative_to(managed_root) / source_b.name

    assert not projected_a.exists()
    assert projected_b.exists()
    assert projected_b.samefile(source_b)


@pytest.mark.e2e
def test_radarr_e2e_projection_multi_mapping() -> None:
    case_root = _resolve_case_root(f"radarr_projection_multi_mapping_{uuid.uuid4().hex[:8]}")

    managed_a = case_root / "managed_a"
    managed_b = case_root / "managed_b"
    library_a = case_root / "library_a"
    library_b = case_root / "library_b"
    managed_a.mkdir(parents=True, exist_ok=True)
    managed_b.mkdir(parents=True, exist_ok=True)
    library_a.mkdir(parents=True, exist_ok=True)
    library_b.mkdir(parents=True, exist_ok=True)

    radarr_url = os.getenv("LIBRARIARR_RADARR_E2E_URL", "http://radarr-test:7878").rstrip("/")
    api_key = _wait_for_api_key(Path("/radarr-config/config.xml"))
    session = _wait_for_radarr(radarr_url, api_key)

    movie_a = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_a,
        title="Fixture Projection Mapping A",
        title_slug="fixture-projection-mapping-a-2023",
        tmdb_id=635302,
        year=2023,
    )
    movie_b = _seed_movie_or_skip(
        session,
        radarr_url,
        managed_b,
        title="Fixture Projection Mapping B",
        title_slug="fixture-projection-mapping-b-2024",
        tmdb_id=616036,
        year=2024,
    )

    movie_a = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_a,
        managed_a,
        "mapping-a",
    )
    movie_b = _ensure_movie_path_under_managed_root(
        session,
        radarr_url,
        movie_b,
        managed_b,
        "mapping-b",
    )

    folder_a = Path(str(movie_a["path"]))
    folder_b = Path(str(movie_b["path"]))
    folder_a.mkdir(parents=True, exist_ok=True)
    folder_b.mkdir(parents=True, exist_ok=True)
    source_a = folder_a / "Fixture.Projection.Mapping.A.2023.1080p.x265.mkv"
    source_b = folder_b / "Fixture.Projection.Mapping.B.2024.1080p.x265.mkv"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")

    config = AppConfig(
        paths=PathsConfig(
            series_root_mappings=[],
            movie_root_mappings=[
                MovieRootMapping(managed_root=str(managed_a), library_root=str(library_a)),
                MovieRootMapping(managed_root=str(managed_b), library_root=str(library_b)),
            ],
        ),
        radarr=RadarrConfig(
            url=radarr_url,
            api_key=api_key,
            sync_enabled=True,
            projection=RadarrProjectionConfig(),
        ),
        cleanup=CleanupConfig(remove_orphaned_links=True),
        runtime=RuntimeConfig(debounce_seconds=1, maintenance_interval_minutes=60),
    )

    service = LibrariArrService(config)
    service.reconcile()

    folder_name_a = safe_path_component("Fixture Projection Mapping A (2023)")
    folder_name_b = safe_path_component("Fixture Projection Mapping B (2024)")
    projected_a = library_a / folder_name_a / source_a.name
    projected_b = library_b / folder_name_b / source_b.name

    assert projected_a.exists()
    assert projected_a.samefile(source_a)
    assert projected_b.exists()
    assert projected_b.samefile(source_b)
    assert not (library_b / folder_a.name / source_a.name).exists()
    assert not (library_a / folder_b.name / source_b.name).exists()
