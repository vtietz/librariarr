from pathlib import Path

import requests

from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config


def test_reconcile_continues_when_radarr_update_returns_400(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    movie_a = nested_root / "Fixture Catalog A (2008)"
    movie_b = nested_root / "Fixture Catalog B (2009)"
    movie_a.mkdir(parents=True)
    movie_b.mkdir(parents=True)
    (movie_a / "Fixture.Catalog.A.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")
    (movie_b / "Fixture.Catalog.B.2009.1080p.x265.mkv").write_text("x", encoding="utf-8")

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    fake = FakeRadarr(
        movies=[
            {
                "id": 120,
                "title": "Fixture Catalog A",
                "year": 2008,
                "path": "/old/path/a",
                "movieFile": {"id": 11},
                "monitored": True,
            },
            {
                "id": 121,
                "title": "Fixture Catalog B",
                "year": 2009,
                "path": "/old/path/b",
                "movieFile": {"id": 12},
                "monitored": True,
            },
        ]
    )

    original_update = fake.update_movie_path

    def _update_with_bad_request(movie: dict, new_path: str) -> bool:
        if int(movie.get("id") or 0) == 120:
            response = requests.Response()
            response.status_code = 400
            response.url = "http://radarr:7878/api/v3/movie/120"
            raise requests.HTTPError("400 Client Error: Bad Request", response=response)
        return original_update(movie, new_path)

    fake.update_movie_path = _update_with_bad_request  # type: ignore[method-assign]
    service.radarr = fake
    caplog.set_level("WARNING", logger="librariarr.service")

    service.reconcile()

    assert (shadow_root / "Fixture Catalog A (2008)").is_symlink()
    assert (shadow_root / "Fixture Catalog B (2009)").is_symlink()
    assert 120 not in fake.refreshed
    assert 121 in fake.refreshed
    assert "Skipping Radarr sync for movie id=120" in caplog.text
