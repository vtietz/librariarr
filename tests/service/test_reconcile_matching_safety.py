from pathlib import Path

from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config


def test_reconcile_does_not_fuzzy_match_short_substring_titles(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_dir = nested_root / "Saw I (2004)"
    movie_dir.mkdir(parents=True)
    (movie_dir / "Saw.I.2004.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(
        nested_root,
        shadow_root,
        sync_enabled=True,
        auto_add_unmatched=False,
    )
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 99,
                "title": "The Saw Doctors in Concert - Live in Galway",
                "year": 2004,
                "path": "/old/path",
                "movieFile": {"id": 199},
                "monitored": True,
            }
        ]
    )
    service.radarr = fake
    caplog.set_level("WARNING", logger="librariarr.service")

    service.reconcile()

    assert (shadow_root / "Saw I (2004)").is_symlink()
    assert fake.updated_paths == []
    assert "No Radarr match for folder:" in caplog.text
