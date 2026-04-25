from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .models import MappingProbeResult, MovieProjectionMapping


def probe_movie_root_mappings(
    mappings: list[MovieProjectionMapping],
) -> dict[tuple[str, str], MappingProbeResult]:
    probes: dict[tuple[str, str], MappingProbeResult] = {}
    for mapping in mappings:
        probe = _probe_single_mapping(mapping)
        probes[(str(mapping.managed_root), str(mapping.library_root))] = probe
    return probes


def _probe_single_mapping(mapping: MovieProjectionMapping) -> MappingProbeResult:
    managed_root = mapping.managed_root
    library_root = mapping.library_root
    managed_root.mkdir(parents=True, exist_ok=True)
    library_root.mkdir(parents=True, exist_ok=True)

    hardlink_capable = _is_same_device(managed_root, library_root)
    managed_writable = os.access(managed_root, os.W_OK)
    library_writable = os.access(library_root, os.W_OK)
    library_temp_write_ok = _can_write_temp_file(library_root)
    library_free_bytes = _free_bytes(library_root)

    return MappingProbeResult(
        managed_root=managed_root,
        library_root=library_root,
        hardlink_capable=hardlink_capable,
        managed_writable=managed_writable,
        library_writable=library_writable,
        library_temp_write_ok=library_temp_write_ok,
        library_free_bytes=library_free_bytes,
    )


def _is_same_device(left: Path, right: Path) -> bool:
    try:
        return left.stat().st_dev == right.stat().st_dev
    except OSError:
        return False


def _can_write_temp_file(root: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(prefix=".librariarr-probe-", dir=root, delete=True):
            return True
    except OSError:
        return False


def _free_bytes(root: Path) -> int:
    try:
        stat = os.statvfs(root)
        return int(stat.f_bavail * stat.f_frsize)
    except OSError:
        return 0
