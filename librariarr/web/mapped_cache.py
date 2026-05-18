from __future__ import annotations

from ..cache import mapped_cache as _impl


def __getattr__(name: str):
    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_impl)))


__all__ = [name for name in dir(_impl) if not name.startswith("__")]
