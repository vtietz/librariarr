"""Arr never rewrites its own path on a managed-tree rename (invariant #3);
list_path_differences surfaces that expected mismatch instead of leaving it
looking like a bug. Read-only: uses the advisory cache, no tree walk.
"""

from __future__ import annotations

from librariarr.core.engine import ReconcileEngine

from .conftest import FakeRadarr, FakeSonarr


def test_reports_movie_whose_managed_folder_was_renamed(config, roots, cache):
    library_folder = roots["library_movies"] / "Foo (2020)"
    managed_folder = roots["managed_movies"] / "Foo (2020) custom name"
    library_folder.mkdir()
    managed_folder.mkdir()
    cache.set_folder("radarr", 1, managed_folder)
    radarr = FakeRadarr([{"id": 1, "title": "Foo", "path": str(library_folder)}])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)

    differences = engine.list_path_differences()

    assert differences == [
        {
            "kind": "movie",
            "title": "Foo",
            "arr_path": str(library_folder),
            "managed_path": str(managed_folder),
        }
    ]


def test_no_difference_when_names_match(config, roots, cache):
    library_folder = roots["library_movies"] / "Foo (2020)"
    managed_folder = roots["managed_movies"] / "Foo (2020)"
    library_folder.mkdir()
    managed_folder.mkdir()
    cache.set_folder("radarr", 1, managed_folder)
    radarr = FakeRadarr([{"id": 1, "title": "Foo", "path": str(library_folder)}])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)

    assert engine.list_path_differences() == []


def test_ignores_items_with_no_cached_managed_folder(config, roots, cache):
    library_folder = roots["library_movies"] / "Foo (2020)"
    library_folder.mkdir()
    radarr = FakeRadarr([{"id": 1, "title": "Foo", "path": str(library_folder)}])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)

    assert engine.list_path_differences() == []


def test_reports_series_whose_managed_folder_was_renamed(config, roots, cache):
    shadow_folder = roots["shadow_series"] / "Show (2020)"
    managed_folder = roots["managed_series"] / "Show (2020) custom name"
    shadow_folder.mkdir()
    managed_folder.mkdir()
    cache.set_folder("sonarr", 1, managed_folder)
    sonarr = FakeSonarr([{"id": 1, "title": "Show", "path": str(shadow_folder)}])
    engine = ReconcileEngine(config, radarr=None, sonarr=sonarr, cache=cache)

    differences = engine.list_path_differences()

    assert differences == [
        {
            "kind": "series",
            "title": "Show",
            "arr_path": str(shadow_folder),
            "managed_path": str(managed_folder),
        }
    ]
