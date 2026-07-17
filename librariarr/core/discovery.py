"""Discovery of unmatched managed folders and conservative auto-add.

Name parsing is only used at first contact (to look a folder up in Arr); once
an item is linked, inode identity takes over and names never matter again.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from ..config.models import AppConfig
from ..sync.naming import extract_title_year
from .fsops import (
    TRASH_DIR_NAME,
    ensure_hardlink,
    inode_of,
    is_excluded,
    is_video_file,
    is_within,
    iter_files,
    matches_extras_allowlist,
)
from .index import AdvisoryCache
from .model import Action, ReconcileReport, UnmatchedFolder

LOG = logging.getLogger(__name__)

SEASON_DIR_RE = re.compile(r"^((season|staffel)[\s._-]*\d+|specials?)$", re.IGNORECASE)


def _excluded(path: Path, config: AppConfig) -> bool:
    return is_excluded(path, config.paths.exclude_paths)


def find_movie_folder_candidates(
    managed_root: Path, video_extensions: list[str], config: AppConfig
) -> list[Path]:
    """Directories directly containing at least one video file (topmost wins)."""
    candidates: list[Path] = []
    if not managed_root.is_dir():
        return candidates
    for dirpath, dirnames, filenames in os.walk(managed_root):
        directory = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d != TRASH_DIR_NAME]
        if _excluded(directory, config):
            dirnames[:] = []
            continue
        has_video = any(
            is_video_file(directory / name, video_extensions)
            and not _excluded(directory / name, config)
            for name in filenames
        )
        if has_video and directory != managed_root:
            candidates.append(directory)
            dirnames[:] = []  # a movie folder's subtree belongs to it (extras etc.)
    return candidates


def find_series_folder_candidates(
    managed_root: Path,
    video_extensions: list[str],
    known_inodes: set[int],
    config: AppConfig,
) -> list[Path]:
    """Highest directories below the root whose video files are ALL unknown to Arr."""
    total: dict[Path, int] = {}
    unknown: dict[Path, int] = {}
    for file_path in iter_files(managed_root):
        if not is_video_file(file_path, video_extensions) or _excluded(file_path, config):
            continue
        inode = inode_of(file_path)
        is_unknown = inode is not None and inode not in known_inodes
        directory = file_path.parent
        while directory != managed_root and is_within(directory, managed_root):
            total[directory] = total.get(directory, 0) + 1
            if is_unknown:
                unknown[directory] = unknown.get(directory, 0) + 1
            directory = directory.parent

    raw_candidates: list[Path] = []
    for directory, count in total.items():
        if unknown.get(directory, 0) != count:
            continue  # contains known files; not a candidate
        parent = directory.parent
        parent_all_unknown = (
            parent != managed_root
            and is_within(parent, managed_root)
            and unknown.get(parent, 0) == total.get(parent, -1)
        )
        if parent_all_unknown:
            continue  # parent is the higher candidate

        for refined in _refine_series_candidate(directory, video_extensions, config):
            if refined not in raw_candidates:
                raw_candidates.append(refined)
    return sorted(raw_candidates)


def _refine_series_candidate(
    directory: Path, video_extensions: list[str], config: AppConfig
) -> list[Path]:
    """Descend from a grouping folder to the actual series folder(s).

    A series folder either directly contains video files or contains
    season-like subfolders. Anything above that is a grouping level.
    """
    has_direct_video = any(
        entry.is_file() and is_video_file(entry, video_extensions) and not _excluded(entry, config)
        for entry in directory.iterdir()
    )
    if has_direct_video:
        return [directory]
    subdirs = [
        entry
        for entry in sorted(directory.iterdir())
        if entry.is_dir()
        and entry.name != TRASH_DIR_NAME
        and not _excluded(entry, config)
        and any(is_video_file(f, video_extensions) for f in iter_files(entry))
    ]
    if not subdirs:
        return []
    if all(SEASON_DIR_RE.match(entry.name) for entry in subdirs):
        return [directory]
    return [
        refined
        for entry in subdirs
        for refined in _refine_series_candidate(entry, video_extensions, config)
    ]


class MovieDiscovery:
    def __init__(self, config: AppConfig, radarr, cache: AdvisoryCache) -> None:
        self.config = config
        self.radarr = radarr
        self.cache = cache
        self.video_extensions = config.radarr.projection.managed_video_extensions
        self.extras_allowlist = config.radarr.projection.managed_extras_allowlist

    def run(
        self,
        movies: list[dict],
        arr_inodes: set[int],
        report: ReconcileReport,
        dry_run: bool,
        progress=None,
    ) -> None:
        tick = progress or (lambda phase, current, total: None)
        candidates = [
            (folder, mapping)
            for mapping in self.config.paths.movie_root_mappings
            for folder in find_movie_folder_candidates(
                Path(mapping.managed_root), self.video_extensions, self.config
            )
        ]
        for idx, (folder, mapping) in enumerate(candidates, start=1):
            tick("discovery (movies)", idx, len(candidates))
            inodes = {
                inode
                for f in iter_files(folder)
                if is_video_file(f, self.video_extensions) and (inode := inode_of(f)) is not None
            }
            if not inodes or inodes & arr_inodes:
                continue
            self._handle_unmatched(folder, Path(mapping.library_root), movies, report, dry_run)

    def manual_add(self, folder: Path, library_root: Path, report: ReconcileReport) -> None:
        """User-initiated add of one folder: bypasses the auto_add_unmatched gate."""
        movies = self.radarr.get_movies()
        self._handle_unmatched(folder, library_root, movies, report, dry_run=False, force_add=True)

    def _handle_unmatched(
        self,
        folder: Path,
        library_root: Path,
        movies: list[dict],
        report: ReconcileReport,
        dry_run: bool,
        force_add: bool = False,
    ) -> None:
        parsed = extract_title_year(folder.name)
        if parsed is None:
            report.unmatched.append(UnmatchedFolder(str(folder), None, None, reason="unparseable"))
            return
        title, year = parsed

        if self._adopt_existing_movie(folder, library_root, title, year, movies, report, dry_run):
            return

        if not self.config.radarr.auto_add_unmatched and not force_add:
            report.unmatched.append(
                UnmatchedFolder(str(folder), title, year, reason="auto_add_disabled")
            )
            return
        self._auto_add(folder, library_root, title, year, movies, report, dry_run)

    def _adopt_existing_movie(
        self,
        folder: Path,
        library_root: Path,
        title: str,
        year: int,
        movies: list[dict],
        report: ReconcileReport,
        dry_run: bool,
    ) -> bool:
        """Link the folder to an existing Radarr movie with the exact same title+year.

        Returns True when the folder was handled (adopted or reported), so no
        auto-add must be attempted — adding an existing movie can only fail.
        """
        matches = [
            m
            for m in movies
            if (m.get("title") or "").lower() == title.lower() and int(m.get("year") or 0) == year
        ]
        if not matches:
            return False
        movie = self._preferred_match(matches, library_root)
        if not (movie.get("movieFile") or {}).get("path"):
            self._adopt_fileless_movie(folder, movie, report, dry_run)
            return True
        return self._adopt_movie_with_file(folder, library_root, title, year, movie, report)

    @staticmethod
    def _preferred_match(matches: list[dict], library_root: Path) -> dict:
        def rank(movie: dict) -> tuple[int, int]:
            has_file = 1 if (movie.get("movieFile") or {}).get("path") else 0
            in_bucket = 0 if is_within(Path(movie.get("path") or "/"), library_root) else 1
            return (has_file, in_bucket)

        return min(matches, key=rank)

    def _adopt_fileless_movie(
        self,
        folder: Path,
        movie: dict,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        library_folder = Path(movie["path"])
        self._project_all(folder, library_folder, report, dry_run)
        report.add(
            Action(
                "adopt",
                f"linked to file-less Radarr movie '{movie['title']}'",
                str(folder),
                str(library_folder),
            )
        )
        self.cache.set_folder("radarr", int(movie["id"]), folder)
        if not dry_run:
            self.radarr.refresh_movie(int(movie["id"]))

    def _adopt_movie_with_file(
        self,
        folder: Path,
        library_root: Path,
        title: str,
        year: int,
        movie: dict,
        report: ReconcileReport,
    ) -> bool:
        """The matching Radarr movie already has a file (not linked to this folder)."""
        cached = self.cache.get_folder("radarr", int(movie["id"]))
        if cached is not None and cached != folder and cached.is_dir():
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="duplicate",
                    candidates=[f"'{movie['title']}' is already synced from {cached}"],
                )
            )
            return True
        movie_path = Path(movie.get("path") or "")
        if not is_within(movie_path, library_root):
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="already_in_arr",
                    candidates=[
                        f"exists in Radarr at {movie_path}; move its root folder to "
                        f"{library_root} in Radarr (without moving files) so it can be linked"
                    ],
                )
            )
            return True
        report.add(
            Action(
                "adopt",
                f"linked to existing Radarr movie '{movie['title']}'; "
                "files reconcile on the next pass",
                str(folder),
                str(movie_path),
            )
        )
        self.cache.set_folder("radarr", int(movie["id"]), folder)
        return True

    def _auto_add(
        self,
        folder: Path,
        library_root: Path,
        title: str,
        year: int,
        movies: list[dict],
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        profile_id = self.config.radarr.auto_add_quality_profile_id
        if profile_id is None:
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="auto_add_disabled",
                    candidates=["auto_add_quality_profile_id is not configured"],
                )
            )
            return
        try:
            results = self.radarr.lookup_movies(f"{title} ({year})")
        except Exception as exc:  # noqa: BLE001 - lookup failures must not stop reconcile
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder), title, year, reason="lookup_failed", candidates=[str(exc)]
                )
            )
            return
        exact = [
            r
            for r in results
            if (r.get("title") or "").lower() == title.lower() and int(r.get("year") or 0) == year
        ]
        if len(exact) != 1:
            reason = "no_match" if not exact else "ambiguous"
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason=reason,
                    candidates=[f"{r.get('title')} ({r.get('year')})" for r in results[:5]],
                )
            )
            return

        lookup = exact[0]
        existing = self._existing_by_tmdb(lookup, movies)
        if existing is not None:
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="already_in_arr",
                    candidates=[
                        f"already in Radarr as '{existing.get('title')}' at {existing.get('path')}"
                    ],
                )
            )
            return
        target_path = library_root / f"{title} ({year})"
        report.add(
            Action("add_to_arr", f"auto-add '{title} ({year})'", str(folder), str(target_path))
        )
        if dry_run:
            return
        try:
            added = self.radarr.add_movie_from_lookup(
                lookup,
                path=str(target_path),
                root_folder_path=str(library_root),
                quality_profile_id=int(profile_id),
                monitored=self.config.radarr.auto_add_monitored,
                search_for_movie=self.config.radarr.auto_add_search_on_add,
            )
        except Exception as exc:  # noqa: BLE001 - add failures must not stop reconcile
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="add_failed",
                    candidates=[str(exc)],
                )
            )
            report.warn(f"radarr auto-add failed for '{title} ({year})': {exc}")
            return
        movie_id = added.get("id")
        added_path = Path(added.get("path") or target_path)
        self._project_all(folder, added_path, report, dry_run)
        if movie_id:
            self.cache.set_folder("radarr", int(movie_id), folder)
            self.radarr.refresh_movie(int(movie_id))

    @staticmethod
    def _existing_by_tmdb(lookup: dict, movies: list[dict]) -> dict | None:
        tmdb_id = lookup.get("tmdbId")
        if not tmdb_id:
            return None
        return next((m for m in movies if m.get("tmdbId") == tmdb_id), None)

    def _project_all(
        self,
        managed_folder: Path,
        library_folder: Path,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        _project_folder(
            managed_folder,
            library_folder,
            self.video_extensions,
            self.extras_allowlist,
            report,
            dry_run,
        )


def _project_folder(
    managed_folder: Path,
    library_folder: Path,
    video_extensions: list[str],
    extras_allowlist: list[str],
    report: ReconcileReport,
    dry_run: bool,
) -> None:
    for file_path in iter_files(managed_folder):
        is_video = is_video_file(file_path, video_extensions)
        if not is_video and not matches_extras_allowlist(file_path.name, extras_allowlist):
            continue
        target = library_folder / file_path.relative_to(managed_folder)
        if ensure_hardlink(file_path, target, dry_run=dry_run):
            report.items_changed += 1
            report.add(Action("link", "projected to library", str(file_path), str(target)))


class SeriesDiscovery:
    def __init__(self, config: AppConfig, sonarr, cache: AdvisoryCache) -> None:
        self.config = config
        self.sonarr = sonarr
        self.cache = cache
        self.video_extensions = config.sonarr.projection.managed_video_extensions
        self.extras_allowlist = config.sonarr.projection.managed_extras_allowlist

    def run(
        self,
        series_list: list[dict],
        arr_inodes: set[int],
        report: ReconcileReport,
        dry_run: bool,
        progress=None,
    ) -> None:
        tick = progress or (lambda phase, current, total: None)
        candidates = [
            (folder, mapping)
            for mapping in self.config.paths.series_root_mappings
            for folder in find_series_folder_candidates(
                Path(mapping.managed_root), self.video_extensions, arr_inodes, self.config
            )
        ]
        for idx, (folder, mapping) in enumerate(candidates, start=1):
            tick("discovery (series)", idx, len(candidates))
            self._handle_unmatched(folder, Path(mapping.library_root), series_list, report, dry_run)

    def manual_add(self, folder: Path, library_root: Path, report: ReconcileReport) -> None:
        """User-initiated add of one folder: bypasses the auto_add_unmatched gate."""
        series_list = self.sonarr.get_series()
        self._handle_unmatched(
            folder, library_root, series_list, report, dry_run=False, force_add=True
        )

    def _handle_unmatched(
        self,
        folder: Path,
        library_root: Path,
        series_list: list[dict],
        report: ReconcileReport,
        dry_run: bool,
        force_add: bool = False,
    ) -> None:
        parsed = extract_title_year(folder.name)
        title = parsed[0] if parsed else folder.name.strip()
        year = parsed[1] if parsed else None

        fileless = [
            s
            for s in series_list
            if int((s.get("statistics") or {}).get("episodeFileCount") or 0) == 0
        ]
        if self._adopt_fileless_series(folder, title, year, fileless, report, dry_run):
            return
        if not self.config.sonarr.auto_add_unmatched and not force_add:
            report.unmatched.append(
                UnmatchedFolder(str(folder), title, year, reason="auto_add_disabled")
            )
            return
        self._auto_add(folder, library_root, title, year, series_list, report, dry_run)

    def _adopt_fileless_series(
        self,
        folder: Path,
        title: str,
        year: int | None,
        fileless: list[dict],
        report: ReconcileReport,
        dry_run: bool,
    ) -> bool:
        for series in fileless:
            if (series.get("title") or "").lower() != title.lower():
                continue
            if year is not None and int(series.get("year") or 0) not in (0, year):
                continue
            shadow_folder = Path(series["path"])
            _project_folder(
                folder,
                shadow_folder,
                self.video_extensions,
                self.extras_allowlist,
                report,
                dry_run,
            )
            report.add(
                Action(
                    "adopt",
                    f"linked to file-less Sonarr series '{series['title']}'",
                    str(folder),
                    str(shadow_folder),
                )
            )
            self.cache.set_folder("sonarr", int(series["id"]), folder)
            if not dry_run:
                self.sonarr.refresh_series(int(series["id"]))
            return True
        return False

    def _auto_add(
        self,
        folder: Path,
        library_root: Path,
        title: str,
        year: int | None,
        series_list: list[dict],
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        profile_id = self.config.sonarr.auto_add_quality_profile_id
        if profile_id is None:
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="auto_add_disabled",
                    candidates=["auto_add_quality_profile_id is not configured"],
                )
            )
            return
        try:
            results = self.sonarr.lookup_series(title)
        except Exception as exc:  # noqa: BLE001 - lookup failures must not stop reconcile
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder), title, year, reason="lookup_failed", candidates=[str(exc)]
                )
            )
            return
        exact = [
            r
            for r in results
            if (r.get("title") or "").lower() == title.lower()
            and (year is None or int(r.get("year") or 0) == year)
        ]
        if len(exact) != 1:
            reason = "no_match" if not exact else "ambiguous"
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason=reason,
                    candidates=[f"{r.get('title')} ({r.get('year')})" for r in results[:5]],
                )
            )
            return

        lookup = exact[0]
        tvdb_id = lookup.get("tvdbId")
        existing = (
            next((s for s in series_list if tvdb_id and s.get("tvdbId") == tvdb_id), None)
            if tvdb_id
            else None
        )
        if existing is not None:
            report.unmatched.append(
                UnmatchedFolder(
                    str(folder),
                    title,
                    year,
                    reason="already_in_arr",
                    candidates=[
                        f"already in Sonarr as '{existing.get('title')}' at {existing.get('path')}"
                    ],
                )
            )
            return
        folder_title = lookup.get("title") or title
        lookup_year = lookup.get("year")
        suffix = f" ({lookup_year})" if lookup_year else ""
        target_path = library_root / f"{folder_title}{suffix}"
        report.add(
            Action("add_to_arr", f"auto-add series '{folder_title}'", str(folder), str(target_path))
        )
        if dry_run:
            return
        added = self.sonarr.add_series_from_lookup(
            lookup,
            path=str(target_path),
            root_folder_path=str(library_root),
            quality_profile_id=int(profile_id),
            language_profile_id=self.config.sonarr.auto_add_language_profile_id,
            monitored=self.config.sonarr.auto_add_monitored,
            season_folder=self.config.sonarr.auto_add_season_folder,
            search_for_missing_episodes=self.config.sonarr.auto_add_search_on_add,
        )
        series_id = added.get("id")
        added_path = Path(added.get("path") or target_path)
        _project_folder(
            folder,
            added_path,
            self.video_extensions,
            self.extras_allowlist,
            report,
            dry_run,
        )
        if series_id:
            self.cache.set_folder("sonarr", int(series_id), folder)
            self.sonarr.refresh_series(int(series_id))
