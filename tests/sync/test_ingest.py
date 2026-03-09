from pathlib import Path

from librariarr.config import IngestConfig
from librariarr.sync.ingest import ShadowIngestor


def test_ingestor_moves_real_shadow_folder_and_replaces_symlink(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    incoming = shadow_root / "Incoming Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "Incoming.Movie.2024.1080p.mkv").write_text("x", encoding="utf-8")

    ingestor = ShadowIngestor(
        config=IngestConfig(enabled=True, min_age_seconds=0),
        video_exts={".mkv"},
        shadow_roots=[shadow_root],
        shadow_to_nested_roots={shadow_root: [nested_root]},
    )

    ingested = ingestor.run()

    destination = nested_root / "Incoming Movie (2024)"
    shadow_link = shadow_root / "Incoming Movie (2024)"
    assert ingested == 1
    assert destination.exists()
    assert shadow_link.is_symlink()
    assert shadow_link.resolve(strict=False) == destination


def test_ingestor_collision_skip_leaves_source_folder(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_root = tmp_path / "nested"
    existing = nested_root / "Collision Movie (2024)"
    existing.mkdir(parents=True)
    (existing / "existing.mkv").write_text("x", encoding="utf-8")

    incoming = shadow_root / "Collision Movie (2024)"
    incoming.mkdir(parents=True)
    (incoming / "incoming.mkv").write_text("x", encoding="utf-8")

    ingestor = ShadowIngestor(
        config=IngestConfig(enabled=True, min_age_seconds=0, collision_policy="skip"),
        video_exts={".mkv"},
        shadow_roots=[shadow_root],
        shadow_to_nested_roots={shadow_root: [nested_root]},
    )

    ingested = ingestor.run()

    assert ingested == 0
    assert incoming.exists()
    assert incoming.is_dir()
    assert not incoming.is_symlink()


def test_ingestor_skips_when_shadow_root_maps_to_multiple_nested_roots(tmp_path: Path) -> None:
    shadow_root = tmp_path / "radarr_library"
    nested_a = tmp_path / "nested_a"
    nested_b = tmp_path / "nested_b"

    movie_a = shadow_root / "Movie A (2020)"
    movie_b = shadow_root / "Movie B (2021)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)
    (movie_a / "movie.a.2020.mkv").write_text("x", encoding="utf-8")
    (movie_b / "movie.b.2021.mkv").write_text("x", encoding="utf-8")

    ingestor = ShadowIngestor(
        config=IngestConfig(enabled=True, min_age_seconds=0),
        video_exts={".mkv"},
        shadow_roots=[shadow_root],
        shadow_to_nested_roots={shadow_root: [nested_a, nested_b]},
    )

    ingested = ingestor.run()

    assert ingested == 0
    assert movie_a.exists()
    assert movie_b.exists()
