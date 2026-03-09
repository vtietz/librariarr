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
NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9._-]+")


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
        self.sync_enabled = config.radarr.sync_enabled
        self.radarr = RadarrClient(config.radarr.url, config.radarr.api_key)
        self.root_mappings = self._build_root_mappings(config)
        self.nested_roots = [nested for nested, _ in self.root_mappings]
        self.shadow_roots = self._unique_paths([shadow for _, shadow in self.root_mappings])
        self.video_exts = set(config.runtime.scan_video_extensions or VIDEO_EXTENSIONS)

        self._debounce_seconds = max(1, config.runtime.debounce_seconds)
        maintenance_minutes = config.runtime.maintenance_interval_minutes
        # 0 or negative disables periodic maintenance; startup + FS events still run.
        self._maintenance_interval = (
            None if maintenance_minutes <= 0 else max(60, maintenance_minutes * 60)
        )
        self._last_event = 0.0
        self._last_sync = 0.0
        self._lock = threading.Lock()

    def _build_root_mappings(self, config: AppConfig) -> list[tuple[Path, Path]]:
        mappings: list[tuple[Path, Path]] = []

        if config.paths.root_mappings:
            for item in config.paths.root_mappings:
                mappings.append((Path(item.nested_root), Path(item.shadow_root)))
            return mappings

        default_shadow_root = Path(config.radarr.shadow_root)
        for nested_root in config.paths.nested_roots:
            mappings.append((Path(nested_root), default_shadow_root))
        return mappings

    def _unique_paths(self, paths: list[Path]) -> list[Path]:
        seen: set[Path] = set()
        ordered: list[Path] = []
        for path in paths:
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
        return ordered

    def run(self) -> None:
        LOG.info(
            "Starting LibrariArr service: shadow_roots=%s nested_roots=%s "
            "sync_enabled=%s debounce_seconds=%s maintenance_interval_seconds=%s",
            ",".join(str(root) for root in self.shadow_roots),
            ",".join(str(root) for root in self.nested_roots),
            self.sync_enabled,
            self._debounce_seconds,
            self._maintenance_interval if self._maintenance_interval is not None else "disabled",
        )
        for shadow_root in self.shadow_roots:
            shadow_root.mkdir(parents=True, exist_ok=True)
        observer = Observer()
        handler = SyncEventHandler(self.mark_dirty)

        for root in self.nested_roots:
            root.mkdir(parents=True, exist_ok=True)
            observer.schedule(handler, str(root), recursive=True)
            LOG.info("Watching: %s", root)

        observer.start()
        try:
            try:
                self.reconcile()
            except Exception:
                LOG.exception("Initial reconcile failed")

            while True:
                now = time.time()
                should_maintenance = self._maintenance_interval is not None and (
                    (now - self._last_sync) >= self._maintenance_interval
                )
                should_event_sync = self._last_event and (
                    (now - self._last_event) >= self._debounce_seconds
                )

                if should_maintenance or should_event_sync:
                    if should_maintenance:
                        LOG.info("Running scheduled maintenance reconcile")
                    if should_event_sync:
                        LOG.info("Running event-triggered reconcile")
                    try:
                        self.reconcile()
                    except Exception:
                        LOG.exception("Reconcile failed; will retry on next cycle")
                    self._last_event = 0.0
                time.sleep(1)
        finally:
            observer.stop()
            observer.join()

    def mark_dirty(self) -> None:
        if self._last_event == 0.0:
            LOG.info(
                "Filesystem change detected; reconciling in ~%ss after debounce",
                self._debounce_seconds,
            )
        self._last_event = time.time()

    def reconcile(self) -> None:
        with self._lock:
            started = time.time()
            LOG.info("Reconciling shadow links and Radarr state...")
            self._last_sync = time.time()
            for shadow_root in self.shadow_roots:
                shadow_root.mkdir(parents=True, exist_ok=True)

            movie_folders = self._all_movie_folders()
            target_to_links = self._current_links()
            movies_by_ref = self._build_movie_index() if self.sync_enabled else {}
            expected_links: set[Path] = set()
            created_links = 0
            matched_movies = 0
            unmatched_movies = 0

            for folder, shadow_root in sorted(movie_folders.items()):
                movie = (
                    self._match_movie_for_folder(folder, movies_by_ref)
                    if self.sync_enabled
                    else None
                )
                existing_links = target_to_links.get(folder, set())
                link_path, was_created = self._ensure_link(
                    folder,
                    shadow_root,
                    existing_links,
                    movie,
                )
                expected_links.add(link_path)
                target_to_links.setdefault(folder, set()).add(link_path)
                if was_created:
                    created_links += 1

                if self.sync_enabled:
                    if movie is not None:
                        self._sync_radarr_for_folder(folder, link_path, movie)
                        matched_movies += 1
                    else:
                        LOG.warning("No Radarr match for folder: %s", folder)
                        unmatched_movies += 1

            orphaned_links_removed = 0
            if self.config.cleanup.remove_orphaned_links:
                orphaned_links_removed = self._cleanup_orphans(
                    set(movie_folders.keys()),
                    movies_by_ref,
                    expected_links,
                )

            duration_seconds = round(time.time() - started, 2)
            LOG.info(
                "Reconcile complete: movie_folders=%s existing_links=%s "
                "created_links=%s matched_movies=%s unmatched_movies=%s "
                "removed_orphans=%s sync_enabled=%s duration_seconds=%s",
                len(movie_folders),
                sum(len(links) for links in target_to_links.values()),
                created_links,
                matched_movies,
                unmatched_movies,
                orphaned_links_removed,
                self.sync_enabled,
                duration_seconds,
            )

    def _all_movie_folders(self) -> dict[Path, Path]:
        all_folders: dict[Path, Path] = {}
        # Prefer more specific nested roots first if mappings overlap.
        sorted_mappings = sorted(
            self.root_mappings,
            key=lambda pair: (-len(pair[0].parts), str(pair[0])),
        )
        for nested_root, shadow_root in sorted_mappings:
            for folder in discover_movie_folders(nested_root, self.video_exts):
                all_folders.setdefault(folder, shadow_root)
        return all_folders

    def _current_links(self) -> dict[Path, set[Path]]:
        out: dict[Path, set[Path]] = {}
        for shadow_root in self.shadow_roots:
            if not shadow_root.exists():
                continue

            for child in shadow_root.iterdir():
                if not child.is_symlink():
                    continue
                try:
                    target = child.resolve(strict=False)
                except OSError:
                    continue
                out.setdefault(target, set()).add(child)
        return out

    def _match_movie_for_folder(
        self,
        folder: Path,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        ref = parse_movie_ref(folder.name)
        return movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))

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

    def _canonical_link_name(self, folder: Path, movie: dict | None) -> str:
        if movie is None:
            return self._safe_link_name(folder)

        title = str(movie.get("title") or "").strip() or folder.name
        year = movie.get("year")
        if isinstance(year, int):
            return f"{title} ({year})"
        return title

    def _normalize_name_part(self, value: str) -> str:
        cleaned = NON_ALNUM_RE.sub("-", value.strip())
        return cleaned.strip("-")

    def _collision_qualifier(self, folder: Path) -> str:
        for root in self.nested_roots:
            try:
                relative = folder.relative_to(root)
            except ValueError:
                continue

            parent_parts = [self._normalize_name_part(part) for part in relative.parts[:-1]]
            qualifier_parts = [self._normalize_name_part(root.name)] + parent_parts
            qualifier = "-".join(part for part in qualifier_parts if part)
            if qualifier:
                return qualifier
        return ""

    def _create_link(self, folder: Path, shadow_root: Path, base_name: str) -> Path:
        candidate = shadow_root / base_name
        qualifier = self._collision_qualifier(folder)
        qualified_candidate = shadow_root / f"{base_name}--{qualifier}" if qualifier else None
        counter = 2

        while candidate.exists() or candidate.is_symlink():
            try:
                if candidate.is_symlink() and candidate.resolve(strict=False) == folder:
                    return candidate
            except OSError:
                pass

            if qualified_candidate is not None:
                candidate = qualified_candidate
                qualified_candidate = None
                continue

            candidate = shadow_root / f"{base_name}--{counter}"
            counter += 1

        candidate.symlink_to(folder, target_is_directory=True)
        LOG.info("Created link: %s -> %s", candidate, folder)
        return candidate

    def _ensure_link(
        self,
        folder: Path,
        shadow_root: Path,
        existing_links: set[Path],
        movie: dict | None,
    ) -> tuple[Path, bool]:
        base_name = self._canonical_link_name(folder, movie)
        desired = shadow_root / base_name

        for link in existing_links:
            if link == desired and link.exists() and link.is_symlink():
                try:
                    if link.resolve(strict=False) == folder:
                        return link, False
                except OSError:
                    pass

        created = not (desired.exists() or desired.is_symlink())
        link = self._create_link(folder, shadow_root, base_name)
        return link, created

    def _sync_radarr_for_folder(
        self,
        folder: Path,
        link: Path,
        movie: dict,
    ) -> None:
        self.radarr.update_movie_path(movie, str(link))
        quality_id = map_quality_id(
            folder,
            self.config.quality_map,
            use_nfo=self.config.analysis.use_nfo,
            use_media_probe=self.config.analysis.use_media_probe,
            media_probe_bin=self.config.analysis.media_probe_bin,
        )
        self.radarr.try_update_moviefile_quality(movie, quality_id)
        self.radarr.refresh_movie(int(movie["id"]))

    def _cleanup_orphans(
        self,
        existing_folders: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        expected_links: set[Path],
    ) -> int:
        removed_count = 0
        for shadow_root in self.shadow_roots:
            if not shadow_root.exists():
                continue

            for child in shadow_root.iterdir():
                if not child.is_symlink():
                    continue

                try:
                    target = child.resolve(strict=False)
                except OSError:
                    target = None
                target_exists = target is not None and target in existing_folders
                link_is_expected = child in expected_links

                if target_exists and link_is_expected:
                    continue

                child.unlink(missing_ok=True)
                removed_count += 1
                LOG.info("Removed orphaned symlink: %s", child)

                # If this is only a stale/renamed duplicate link, do not touch Radarr state.
                if target_exists:
                    continue

                if not self.sync_enabled:
                    continue

                if not self.config.cleanup.unmonitor_on_delete:
                    continue

                ref = parse_movie_ref(child.name.split("--", 1)[0])
                movie = movies_by_ref.get(ref) or movies_by_ref.get(
                    MovieRef(title=ref.title, year=None)
                )
                if movie:
                    if self.config.cleanup.delete_from_radarr_on_missing:
                        self.radarr.delete_movie(int(movie["id"]), delete_files=False)
                        continue
                    self.radarr.unmonitor_movie(movie)
                    self.radarr.refresh_movie(int(movie["id"]))

        return removed_count
