"""Inode index over managed roots and the advisory id->folder cache.

The inode index is rebuilt per discovery pass (one filesystem walk). The
advisory cache maps Arr item ids to managed folders so the frequent
consistency pass can verify identity with two stat calls per item instead of
walking the tree. Cache entries are never trusted: every read is verified
against the live filesystem before use.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from pathlib import Path

from .fsops import inode_of, is_excluded, is_video_file, iter_files

LOG = logging.getLogger(__name__)


class InodeIndex:
    """Maps inode -> managed video file paths (an inode can have several links)."""

    def __init__(self) -> None:
        self._by_inode: dict[int, list[Path]] = {}

    @classmethod
    def build(
        cls,
        roots: Iterable[Path],
        video_extensions: Iterable[str],
        exclude_patterns: Iterable[str] = (),
    ) -> InodeIndex:
        index = cls()
        extensions = list(video_extensions)
        patterns = list(exclude_patterns)
        for root in roots:
            for file_path in iter_files(Path(root)):
                if not is_video_file(file_path, extensions):
                    continue
                if is_excluded(file_path, patterns):
                    continue
                inode = inode_of(file_path)
                if inode is not None:
                    index._by_inode.setdefault(inode, []).append(file_path)
        return index

    def lookup(self, inode: int) -> Path | None:
        paths = self._by_inode.get(inode)
        return paths[0] if paths else None

    def contains(self, inode: int) -> bool:
        return inode in self._by_inode

    def all_inodes(self) -> set[int]:
        return set(self._by_inode)

    def __len__(self) -> int:
        return len(self._by_inode)


class AdvisoryCache:
    """Persisted movie/series id -> managed folder hints. Advisory only.

    Every consumer must stat-verify a hint before acting on it; a stale hint is
    equivalent to a miss. Losing this file entirely only costs one extra
    discovery walk.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, str]] = {"radarr": {}, "sonarr": {}}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for section in ("radarr", "sonarr"):
                entries = raw.get(section)
                if isinstance(entries, dict):
                    self._data[section] = {str(k): str(v) for k, v in entries.items()}

    def save(self) -> None:
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            except OSError as exc:
                LOG.warning("Could not persist advisory cache to %s: %s", self._path, exc)

    def get_folder(self, section: str, item_id: int) -> Path | None:
        value = self._data.get(section, {}).get(str(item_id))
        return Path(value) if value else None

    def set_folder(self, section: str, item_id: int, folder: Path) -> None:
        with self._lock:
            self._data.setdefault(section, {})[str(item_id)] = str(folder)

    def drop(self, section: str, item_id: int) -> None:
        with self._lock:
            self._data.get(section, {}).pop(str(item_id), None)

    def known_folders(self, section: str) -> set[str]:
        return set(self._data.get(section, {}).values())
