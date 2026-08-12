"""Targeted reconcile over a real filesystem: real hardlinks, real renames.

Two things are exercised here that a unit test cannot show: that the narrowed
pass produces the same inode-identity result on disk as the library-wide pass,
and that the drift poll plus targeted reconcile really converge a Radarr
root-folder change end to end — including through the production wiring
(service + runtime loop in a background thread).

Only the Arr HTTP clients are faked.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from librariarr.config.defaults import DEFAULT_EXCLUDE_PATH_PATTERNS
from librariarr.config.models import (
    AppConfig,
    IngestConfig,
    MovieRootMapping,
    PathsConfig,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
    SonarrConfig,
)
from librariarr.core.engine import SCOPE_CONSISTENCY, SCOPE_TARGETED, ReconcileEngine
from librariarr.core.index import AdvisoryCache
from librariarr.runtime.loop import RuntimeLoop
from librariarr.service import LibrariArrService

from .conftest import FakeRadarr, hardlink, write_file

pytestmark = pytest.mark.fs_e2e


def wait_until(predicate, timeout: float = 10.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def move_same_filesystem(source, target):
    """Radarr's "move files" on one filesystem: a rename, so the inode lives on."""
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)
    source.unlink()
    return target


def movie(movie_id: int, title: str, year: int, folder, file_path=None) -> dict:
    payload = {"id": movie_id, "title": title, "year": year, "path": str(folder)}
    if file_path is not None:
        payload["movieFile"] = {"path": str(file_path)}
    return payload


@pytest.fixture
def two_bucket_setup(tmp_path):
    """Two FSK-style buckets, the shape a reclassification needs."""
    buckets = {
        "managed_a": tmp_path / "movies" / "FSK12",
        "library_a": tmp_path / "movies" / ".librariarr" / "FSK12",
        "managed_b": tmp_path / "movies" / "FSK06",
        "library_b": tmp_path / "movies" / ".librariarr" / "FSK06",
        "series_managed": tmp_path / "series" / "FSK12",
        "series_shadow": tmp_path / "series" / ".librariarr" / "FSK12",
    }
    for path in buckets.values():
        path.mkdir(parents=True)
    config = AppConfig(
        paths=PathsConfig(
            movie_root_mappings=[
                MovieRootMapping(
                    managed_root=str(buckets["managed_a"]), library_root=str(buckets["library_a"])
                ),
                MovieRootMapping(
                    managed_root=str(buckets["managed_b"]), library_root=str(buckets["library_b"])
                ),
            ],
            series_root_mappings=[
                RootMapping(
                    managed_root=str(buckets["series_managed"]),
                    library_root=str(buckets["series_shadow"]),
                )
            ],
            exclude_paths=list(DEFAULT_EXCLUDE_PATH_PATTERNS),
        ),
        radarr=RadarrConfig(url="http://radarr:7878", api_key="x"),
        sonarr=SonarrConfig(enabled=False, url="http://sonarr:8989", api_key="x"),
        runtime=RuntimeConfig(
            debounce_seconds=0,
            consistency_interval_seconds=3600,
            full_interval_minutes=600,
            bucket_drift_interval_seconds=0,
            startup_scope="off",
        ),
        ingest=IngestConfig(),
    )
    cache = AdvisoryCache(tmp_path / "idcache.json")
    return buckets, config, cache


def test_targeted_import_creates_the_same_hardlink_identity_as_a_full_library_pass(
    config, cache, roots
):
    """Scenario 1 through the targeted scope, on a real filesystem: the managed
    file and Radarr's file must end up as the same inode."""
    lib_file = write_file(roots["library_movies"] / "Targeted (2021)" / "Targeted.mkv")
    write_file(roots["library_movies"] / "Targeted (2021)" / "movie.nfo", "meta")
    radarr = FakeRadarr([movie(1, "Targeted", 2021, lib_file.parent, lib_file)])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)

    engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])

    managed = roots["managed_movies"] / "Targeted (2021)" / "Targeted.mkv"
    assert managed.stat().st_ino == lib_file.stat().st_ino
    assert managed.stat().st_nlink == 2, "one inode, two links -- data was never copied"
    assert (roots["managed_movies"] / "Targeted (2021)" / "movie.nfo").exists()

    # And it is a fixed point: the library-wide pass has nothing left to do.
    assert engine.run(scope=SCOPE_CONSISTENCY).actions == []


def test_targeted_pass_leaves_every_other_managed_folder_untouched(config, cache, roots):
    """The cost guarantee, measured on disk: nothing outside the named movie is
    read or written (mtimes of the other folders stay put)."""
    named = write_file(roots["library_movies"] / "Named (2021)" / "Named.mkv")
    bystander_managed = write_file(roots["managed_movies"] / "Bystander (2019)" / "By.mkv")
    bystander_lib = hardlink(
        bystander_managed, roots["library_movies"] / "Bystander (2019)" / "By.mkv"
    )
    cache.set_folder("radarr", 2, bystander_managed.parent)
    radarr = FakeRadarr(
        [
            movie(1, "Named", 2021, named.parent, named),
            movie(2, "Bystander", 2019, bystander_lib.parent, bystander_lib),
        ]
    )
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    before = bystander_managed.parent.stat().st_mtime_ns

    engine.run(scope=SCOPE_TARGETED, radarr_movie_ids=[1])

    assert bystander_managed.parent.stat().st_mtime_ns == before
    assert bystander_managed.exists()


def test_bucket_move_converges_through_drift_poll_and_targeted_reconcile(two_bucket_setup):
    """The full chain for the change Radarr reports through no webhook: poll
    detects it, targeted pass applies it, inode identity survives the rename."""
    buckets, config, cache = two_bucket_setup
    managed_file = write_file(buckets["managed_a"] / "Virtual Weapon (1997)" / "VW.mkv")
    write_file(buckets["managed_a"] / "Virtual Weapon (1997)" / "movie.nfo", "meta")
    lib_file = hardlink(managed_file, buckets["library_a"] / "Virtual Weapon (1997)" / "VW.mkv")
    radarr = FakeRadarr([movie(1, "Virtual Weapon", 1997, lib_file.parent, lib_file)])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(config, engine=engine)
    service.reconcile(scope=SCOPE_CONSISTENCY)  # establishes the cache mapping
    original_inode = managed_file.stat().st_ino

    # The user changes the movie's root folder in Radarr ("Move Files").
    new_lib_file = move_same_filesystem(
        lib_file, buckets["library_b"] / "Virtual Weapon (1997)" / "VW.mkv"
    )
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    drift = service.list_bucket_drift()
    assert [entry["id"] for entry in drift] == [1]

    report = service.reconcile_bucket_drift()

    relocated = buckets["managed_b"] / "Virtual Weapon (1997)" / "VW.mkv"
    assert relocated.exists(), "the managed folder must follow into the new bucket"
    assert relocated.stat().st_ino == original_inode, "a rename, not a copy"
    assert relocated.stat().st_ino == new_lib_file.stat().st_ino, "identity with Radarr holds"
    assert (buckets["managed_b"] / "Virtual Weapon (1997)" / "movie.nfo").exists(), (
        "the whole movie folder moves, extras included"
    )
    assert not (buckets["managed_a"] / "Virtual Weapon (1997)").exists()
    assert report is not None and any(action.kind == "relocate" for action in report.actions)

    # Radarr's own file was never touched, and the state is settled.
    assert new_lib_file.exists()
    assert service.list_bucket_drift() == []
    assert service.reconcile(scope=SCOPE_CONSISTENCY).actions == []


def test_bucket_move_is_refused_when_the_destination_is_occupied(two_bucket_setup):
    buckets, config, cache = two_bucket_setup
    managed_file = write_file(buckets["managed_a"] / "Clash (2001)" / "Clash.mkv")
    lib_file = hardlink(managed_file, buckets["library_a"] / "Clash (2001)" / "Clash.mkv")
    occupant = write_file(buckets["managed_b"] / "Clash (2001)" / "someone-elses.mkv")
    radarr = FakeRadarr([movie(1, "Clash", 2001, lib_file.parent, lib_file)])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(config, engine=engine)
    service.reconcile(scope=SCOPE_CONSISTENCY)

    new_lib_file = move_same_filesystem(
        lib_file, buckets["library_b"] / "Clash (2001)" / "Clash.mkv"
    )
    radarr.movies[0]["path"] = str(new_lib_file.parent)
    radarr.movies[0]["movieFile"]["path"] = str(new_lib_file)

    report = service.reconcile_bucket_drift()

    assert managed_file.exists(), "the source must be left exactly where it was"
    assert occupant.exists() and occupant.read_text() == "data", "no merge, no overwrite"
    assert report is not None and not any(action.kind == "relocate" for action in report.actions)
    assert report.stats.get("relocations_blocked_destination_exists") == 1


def test_webhook_shaped_targeted_trigger_converges_through_the_runtime_loop(two_bucket_setup):
    """Production wiring: the loop is what the container runs, and the trigger is
    exactly what POST /api/hooks/radarr issues for a payload naming a movie."""
    buckets, config, cache = two_bucket_setup
    radarr = FakeRadarr([])
    engine = ReconcileEngine(config, radarr=radarr, sonarr=None, cache=cache)
    service = LibrariArrService(config, engine=engine)
    loop = RuntimeLoop(service, config.runtime)
    stop = threading.Event()
    thread = threading.Thread(target=loop.run, args=(stop,), daemon=True)
    thread.start()
    try:
        lib_file = write_file(buckets["library_a"] / "Hooked (2021)" / "Hooked.mkv")
        radarr.movies.append(movie(1, "Hooked", 2021, lib_file.parent, lib_file))

        loop.trigger_targeted("webhook:Download", movie_ids=[1])

        managed = buckets["managed_a"] / "Hooked (2021)" / "Hooked.mkv"
        assert wait_until(managed.exists), "targeted webhook trigger did not converge"
        assert managed.stat().st_ino == lib_file.stat().st_ino
        assert radarr.calls == ["get_movies_by_ids:[1]"], "the loop must not list the library"
    finally:
        stop.set()
        thread.join(timeout=5)
