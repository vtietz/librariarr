"""check_single_filesystem: refuse configs whose roots straddle filesystems.

Hardlinks (and therefore identity/relocation) cannot cross a filesystem
boundary; this guards against the silent-duplicate failure mode a
cross-device move produces, by failing loudly at engine startup instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from librariarr.core.engine import ReconcileEngine
from librariarr.core.fsops import RootFilesystemMismatch, check_single_filesystem


class _FakeStat:
    def __init__(self, st_dev: int) -> None:
        self.st_dev = st_dev


def _patch_devices(monkeypatch, devices: dict[Path, int]) -> None:
    original_stat = Path.stat

    def fake_stat(self, *args, **kwargs):
        if self in devices:
            return _FakeStat(devices[self])
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)


def test_all_roots_on_one_filesystem_passes(monkeypatch, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _patch_devices(monkeypatch, {a: 1, b: 1})

    check_single_filesystem([a, b])  # must not raise


def test_roots_on_different_filesystems_raise(monkeypatch, tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    _patch_devices(monkeypatch, {a: 1, b: 2})

    with pytest.raises(RootFilesystemMismatch, match="filesystem"):
        check_single_filesystem([a, b])


def test_nonexistent_roots_are_skipped_not_errored(tmp_path):
    missing = tmp_path / "does-not-exist-yet"
    check_single_filesystem([missing])  # must not raise


def test_single_root_never_raises(tmp_path):
    only = tmp_path / "only"
    only.mkdir()
    check_single_filesystem([only])


def test_engine_refuses_to_start_when_roots_span_filesystems(monkeypatch, config, roots):
    mismatched = {path: (1 if name == "managed_movies" else 2) for name, path in roots.items()}
    _patch_devices(monkeypatch, mismatched)

    with pytest.raises(RootFilesystemMismatch):
        ReconcileEngine(config, radarr=None, sonarr=None)
