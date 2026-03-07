from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .config import AppConfig
from .quality import VIDEO_EXTENSIONS, map_quality_id
from .radarr import RadarrClient


LOG = logging.getLogger(__name__)
TITLE_YEAR_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")


@dataclass(frozen=True)
class MovieRef:
    title: str
    year: int | None


def parse_movie_ref(name: str) -> MovieRef:
    match = TITLE_YEAR_RE.match(name.strip())
    if not match:
        return MovieRef(title=name.strip().lower(), year=None)
    return MovieRef(title=match.group("title").strip().lower(), year=int(match.group("year")))


def is_movie_folder(path: Path, video_exts: set[str]) -> bool:
    if not path.is_dir():
        return False
    try:
        for child in path.iterdir():
            if child.is_file() and child.suffix.lower() in video_exts:
                return True
    except OSError:
        return False
    return False


def discover_movie_folders(root: Path, video_exts: set[str]) -> set[Path]:
    found: set[Path] = set()
    if not root.exists():
        return found

    for current, dirs, files in __import__("os").walk(root):
        cur_path = Path(current)
        if any(Path(f).suffix.lower() in video_exts for f in files):
            found.add(cur_path)
            dirs[:] = []
    return found


class SyncEventHandler(FileSystemEventHandler):
    def __init__(self, trigger: callable) -> None:
        self.trigger = trigger

    def on_any_event(self, event):  # type: ignore[override]
        self.trigger()


class LibrariArrService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.radarr = RadarrClient(config.radarr.url, config.radarr.api_key)
        self.shadow_root = Path(config.radarr.shadow_root)
        self.nested_roots = [Path(p) for p in config.paths.nested_roots]
        self.video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)

        self._debounce_seconds = max(1, config.runtime.debounce_seconds)
        self._maintenance_interval = max(60, config.runtime.maintenance_interval_minutes * 60)
        self._last_event = 0.0
        self._last_sync = 0.0
        self._lock = threading.Lock()

    def run(self) -> None:
        self.shadow_root.mkdir(parents=True, exist_ok=True)
        observer = Observer()
        handler = SyncEventHandler(self.mark_dirty)

        for root in self.nested_roots:
            root.mkdir(parents=True, exist_ok=True)
            observer.schedule(handler, str(root), recursive=True)
            LOG.info("Watching: %s", root)

        observer.start()
        try:
            self.reconcile()
            while True:
                now = time.time()
                should_maintenance = (now - self._last_sync) >= self._maintenance_interval
                should_event_sync = self._last_event and (now - self._last_event) >= self._debounce_seconds

                if should_maintenance or should_event_sync:
                    self.reconcile()
                    self._last_event = 0.0
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()

    def mark_dirty(self) -> None:
        self._last_event = time.time()

    def reconcile(self) -> None:
        with self._lock:
            LOG.info("Reconciling shadow links and Radarr state...")
            self._last_sync = time.time()

            movie_folders = self._all_movie_folders()
            target_to_link = self._current_links()
            movies_by_ref = self._build_movie_index()

            for folder in sorted(movie_folders):
                link_path = target_to_link.get(folder)
                if link_path is None:
                    link_path = self._create_link(folder)
                self._sync_radarr_for_folder(folder, link_path, movies_by_ref)

            if self.config.cleanup.remove_orphaned_links:
                self._cleanup_orphans(movie_folders, movies_by_ref)

    def _all_movie_folders(self) -> set[Path]:
        all_folders: set[Path] = set()
        for root in self.nested_roots:
            all_folders.update(discover_movie_folders(root, self.video_exts))
        return all_folders

    def _current_links(self) -> dict[Path, Path]:
        out: dict[Path, Path] = {}
        if not self.shadow_root.exists():
            return out

        for child in self.shadow_root.iterdir():
            if not child.is_symlink():
                continue
            try:
                target = child.resolve(strict=False)
            except OSError:
                continue
            out[target] = child
        return out

    def _build_movie_index(self) -> dict[MovieRef, dict]:
        index: dict[MovieRef, dict] = {}
        for movie in self.radarr.get_movies():
            title = (movie.get("title") or "").strip().lower()
            year = movie.get("year")
            ref = MovieRef(title=title, year=year if isinstance(year, int) else None)
            index[ref] = movie
            # Fallback key: title only
            if MovieRef(title=title, year=None) not in index:
                index[MovieRef(title=title, year=None)] = movie
        return index

    def _safe_link_name(self, folder: Path) -> str:
        return folder.name.replace("/", "-").strip()

    def _create_link(self, folder: Path) -> Path:
        base_name = self._safe_link_name(folder)
        candidate = self.shadow_root / base_name
        counter = 2

        while candidate.exists() or candidate.is_symlink():
            try:
                if candidate.is_symlink() and candidate.resolve(strict=False) == folder:
                    return candidate
            except OSError:
                pass
            candidate = self.shadow_root / f"{base_name}--{counter}"
            counter += 1

        candidate.symlink_to(folder, target_is_directory=True)
        LOG.info("Created link: %s -> %s", candidate, folder)
        return candidate

    def _sync_radarr_for_folder(self, folder: Path, link: Path, movies_by_ref: dict[MovieRef, dict]) -> None:
        ref = parse_movie_ref(folder.name)
        movie = movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))
        if not movie:
            LOG.warning("No Radarr match for folder: %s", folder)
            return

        self.radarr.update_movie_path(movie, str(link))
        quality_id = map_quality_id(folder, self.config.quality_map)
        self.radarr.try_update_moviefile_quality(movie, quality_id)
        self.radarr.refresh_movie(int(movie["id"]))

    def _cleanup_orphans(self, existing_folders: set[Path], movies_by_ref: dict[MovieRef, dict]) -> None:
        for child in self.shadow_root.iterdir():
            if not child.is_symlink():
                continue

            try:
                target = child.resolve(strict=False)
            except OSError:
                target = None

            if target and target in existing_folders:
                continue

            child.unlink(missing_ok=True)
            LOG.info("Removed orphaned symlink: %s", child)

            if not self.config.cleanup.unmonitor_on_delete:
                continue

            ref = parse_movie_ref(child.name.split("--", 1)[0])
            movie = movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))
            if movie:
                self.radarr.unmonitor_movie(movie)
                self.radarr.refresh_movie(int(movie["id"]))
