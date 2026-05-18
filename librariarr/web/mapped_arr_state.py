from __future__ import annotations

from ..cache import mapped_arr_state as _impl

# Keep these names monkeypatchable at the legacy import path used by tests.
RadarrClient = _impl.RadarrClient
SonarrClient = _impl.SonarrClient


def enrich_mapped_directories_with_arr_state(*args, **kwargs):
    _impl.RadarrClient = RadarrClient
    _impl.SonarrClient = SonarrClient
    return _impl.enrich_mapped_directories_with_arr_state(*args, **kwargs)


def enrich_mapped_directories_with_radarr_state(*args, **kwargs):
    _impl.RadarrClient = RadarrClient
    return _impl.enrich_mapped_directories_with_radarr_state(*args, **kwargs)


def enrich_mapped_directories_with_sonarr_state(*args, **kwargs):
    _impl.SonarrClient = SonarrClient
    return _impl.enrich_mapped_directories_with_sonarr_state(*args, **kwargs)


def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


__all__ = [
    "RadarrClient",
    "SonarrClient",
    "enrich_mapped_directories_with_arr_state",
    "enrich_mapped_directories_with_radarr_state",
    "enrich_mapped_directories_with_sonarr_state",
]
