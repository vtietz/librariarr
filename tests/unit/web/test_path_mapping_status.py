from pathlib import Path

from librariarr.web.path_mapping_status import build_path_mapping_outcome
from tests.service.helpers import make_config


class _MappedCacheStub:
    def __init__(self, items: list[dict[str, str]]) -> None:
        self._items = items

    def snapshot(self) -> dict[str, list[dict[str, str]]]:
        return {"items": self._items}


def test_build_path_mapping_outcome_uses_provided_inventory_without_arr_calls(
    tmp_path: Path, monkeypatch
) -> None:
    managed_root = tmp_path / "managed"
    library_root = tmp_path / "library"
    managed_root.mkdir()
    library_root.mkdir()

    real_path = managed_root / "Movie One (2020)"
    real_path.mkdir()
    virtual_path = library_root / "Movie One (2020)"

    config = make_config(managed_root, library_root, sync_enabled=True)
    config.radarr.enabled = True
    config.sonarr.enabled = False

    cache = _MappedCacheStub([{"real_path": str(real_path), "virtual_path": str(virtual_path)}])

    class _UnexpectedRadarrClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("RadarrClient should not be created when inventory is provided")

    monkeypatch.setattr(
        "librariarr.web.path_mapping_status.RadarrClient",
        _UnexpectedRadarrClient,
    )

    outcome = build_path_mapping_outcome(
        real_path=str(real_path),
        config=config,
        mapped_cache=cache,
        movies_inventory=[{"id": 12, "title": "Movie One", "path": str(virtual_path)}],
    )

    assert outcome["status"] == "success"
    assert outcome["arr"] == "radarr"
    assert outcome["movie_id"] == 12
