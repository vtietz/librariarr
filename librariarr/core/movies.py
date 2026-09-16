"""Radarr reconcile: inode-identity consistency, ingest, projection, prune.

Identity model: a movie's library file (Radarr-owned name/path) and its managed
counterpart share an inode. Radarr paths are never rewritten; the managed tree
is never renamed by us. See docs/architecture.md.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from ..config.models import AppConfig, MovieRootMapping
from .fsops import (
    ensure_hardlink,
    inode_of,
    is_excluded,
    is_video_file,
    is_within,
    iter_files,
    matches_extras_allowlist,
    prune_empty_dirs,
    remove_file,
)
from .index import AdvisoryCache, InodeIndex
from .model import Action, ReconcileReport
from .relocate import relocate_managed_folder
from .supersede import rescue_replaced_target, supersede_managed_file

LOG = logging.getLogger(__name__)

_PROGRESS_LOG_EVERY = 100


class MovieReconciler:
    def __init__(self, config: AppConfig, radarr, cache: AdvisoryCache) -> None:
        self.config = config
        self.radarr = radarr
        self.cache = cache
        self.video_extensions = config.radarr.projection.managed_video_extensions
        self.extras_allowlist = config.radarr.projection.managed_extras_allowlist
        self.exclude_patterns = config.paths.exclude_paths

    def _relevant_files(self, folder: Path):
        """Files that participate in sync: not excluded (samples, trash, ...)."""
        for file_path in iter_files(folder):
            if not is_excluded(file_path, self.exclude_patterns):
                yield file_path

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def reconcile(
        self,
        report: ReconcileReport,
        *,
        index: InodeIndex | None = None,
        dry_run: bool = False,
        progress=None,
        movie_ids: Sequence[int] | None = None,
    ) -> tuple[list[dict], set[int]]:
        """Reconcile all movies. Returns (movies, arr_known_inodes) for discovery.

        ``movie_ids`` narrows the pass to those Radarr ids (targeted scope).
        Only the iteration narrows: the per-movie decision tree below is
        identical for every scope, so a targeted pass can never reach a
        different conclusion than the pass that covers the whole library.
        """
        movies = self._fetch_movies(movie_ids)
        LOG.info(
            "Radarr reconcile start: movies=%d%s",
            len(movies),
            " (targeted)" if movie_ids is not None else "",
        )
        tick = progress or (lambda phase, current, total: None)
        arr_inodes: set[int] = set()
        for idx, movie in enumerate(movies, start=1):
            tick("movies", idx, len(movies))
            if idx == 1 or idx % _PROGRESS_LOG_EVERY == 0 or idx == len(movies):
                LOG.info(
                    "Radarr progress: %d/%d current='%s'",
                    idx,
                    len(movies),
                    movie.get("title") or "<unknown>",
                )
            mapping = self._mapping_for_library_path(movie.get("path") or "")
            if mapping is None:
                continue
            report.items_seen += 1
            report.bump("movies_total")
            try:
                self._reconcile_movie(movie, mapping, index, arr_inodes, report, dry_run)
            except OSError as exc:
                report.errors.append(f"movie '{movie.get('title')}': {exc}")
        # Pruning decides what to delete from "every folder Radarr no longer
        # lists", so it must never see a partial movie list: with movie_ids set,
        # every folder outside the subset would look stale.
        if index is not None and movie_ids is None:
            self._prune_library_roots(movies, index, report, dry_run)
        self.cache.save()
        return movies, arr_inodes

    def _fetch_movies(self, movie_ids: Sequence[int] | None) -> list[dict]:
        if movie_ids is None:
            return self.radarr.get_movies()
        return self.radarr.get_movies_by_ids(movie_ids)

    # ------------------------------------------------------------------
    # Per-movie reconcile
    # ------------------------------------------------------------------

    def _reconcile_movie(
        self,
        movie: dict,
        mapping: MovieRootMapping,
        index: InodeIndex | None,
        arr_inodes: set[int],
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        movie_id = int(movie["id"])
        movie_file = movie.get("movieFile") or {}
        library_file = Path(movie_file["path"]) if movie_file.get("path") else None
        library_folder = Path(movie["path"])

        if library_file is None:
            report.bump("movies_without_file")
            return  # file-less movie; discovery may pair it with an unmatched folder

        library_inode = inode_of(library_file)
        managed_folder, had_stale_hint = self._verified_managed_folder(movie_id)

        if library_inode is not None:
            arr_inodes.add(library_inode)

        if library_inode is None:
            self._restore_missing_library_file(
                movie, library_file, library_folder, managed_folder, report, dry_run
            )
            return

        source, ambiguous = self._managed_source_for_inode(
            library_inode, managed_folder, index, Path(mapping.managed_root)
        )
        if ambiguous:
            report.warn(
                f"Multiple managed files share Radarr's inode for '{movie.get('title')}'; "
                "deferring reconciliation"
            )
            return
        if source is not None:
            report.bump("movies_in_sync")
            resolved_folder = self._reconcile_bucket(
                movie, self._managed_folder_of(source, managed_folder), mapping, report, dry_run
            )
            self.cache.set_folder("radarr", movie_id, resolved_folder)
            self._project(resolved_folder, library_folder, library_inode, report, dry_run)
            arr_inodes.update(self._folder_video_inodes(resolved_folder))
            return

        # Library inode unknown to the managed tree: ingest or user-replacement.
        if managed_folder is not None:
            # Reconcile the bucket *before* resolving the inode question: a
            # root-folder change can coincide with an unresolved inode (Radarr
            # copied instead of renaming, or an upgrade landed in the same
            # cycle). Relocating first makes the ingest/relink below land in
            # the bucket Radarr now says this movie belongs to, instead of
            # writing into the old bucket and quarantining a file for nothing.
            managed_folder = self._reconcile_bucket(movie, managed_folder, mapping, report, dry_run)
            self.cache.set_folder("radarr", movie_id, managed_folder)
            self._resolve_unknown_inode_with_known_folder(
                movie, library_file, library_folder, managed_folder, report, dry_run
            )
            return

        if had_stale_hint and index is None:
            # This movie was previously located in the managed tree (likely
            # moved/renamed), but its cached folder is gone and a consistency
            # pass has no inode index to relocate it with. Assuming "new
            # import" here would hardlink a duplicate at the default location
            # instead of finding the real, moved file. Defer to the next full
            # pass, which builds the index and resolves it correctly.
            report.warn(
                f"Managed folder for '{movie.get('title')}' could not be located "
                "(likely moved); will resolve on the next full pass"
            )
            return

        self._ingest_new_movie(movie, library_folder, mapping, report, dry_run)

    def _restore_missing_library_file(
        self,
        movie: dict,
        library_file: Path,
        library_folder: Path,
        managed_folder: Path | None,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        """Arr believes it has a file but the library path is gone: reproject."""
        source = self._primary_video(managed_folder) if managed_folder else None
        if source is None:
            report.warn(f"Radarr file missing on disk and no managed source known: {library_file}")
            return
        if ensure_hardlink(source, library_file, dry_run=dry_run):
            report.items_changed += 1
            report.add(
                Action("relink", "restored missing library file", str(source), str(library_file))
            )
            self._project(source.parent, library_folder, inode_of(source), report, dry_run)
            if not dry_run:
                self.radarr.refresh_movie(int(movie["id"]))

    def _resolve_unknown_inode_with_known_folder(
        self,
        movie: dict,
        library_file: Path,
        library_folder: Path,
        managed_folder: Path,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        """Library file inode is not in the managed folder we know for this movie.

        Two possible truths: Radarr wrote a new file (quality upgrade) -> ingest
        wins; or the user replaced the managed file (managed leads) -> relink
        wins. The user replacement only wins when the managed file is newer than
        both the library file's mtime and Radarr's import time (movieFile
        dateAdded, when known): downloaded files often carry the release's
        original, much older mtime, so mtime alone would let a stale managed
        copy clobber a fresh import. Ingest is the safe default — it
        quarantines rather than destroys.
        """
        managed_video = self._primary_video(managed_folder)
        if managed_video is None:
            # Managed folder lost its video: treat the library file as the truth.
            self._ingest_into_folder(movie, library_folder, managed_folder, report, dry_run)
            return

        library_mtime = library_file.stat().st_mtime
        managed_mtime = managed_video.stat().st_mtime
        imported_at = self._movie_file_import_time(movie)
        managed_is_latest = managed_mtime > library_mtime and (
            imported_at is None or managed_mtime > imported_at
        )
        if managed_is_latest:
            report.warn(
                f"Managed file is newer than Radarr's file and its import time for "
                f"'{movie.get('title')}'; relinking library to managed (user replacement wins)"
            )
            if ensure_hardlink(managed_video, library_file, dry_run=dry_run):
                report.items_changed += 1
                report.add(
                    Action(
                        "relink",
                        "user replacement wins over library file",
                        str(managed_video),
                        str(library_file),
                    )
                )
                if not dry_run:
                    self.radarr.refresh_movie(int(movie["id"]))
            return

        self._ingest_into_folder(movie, library_folder, managed_folder, report, dry_run)

    # ------------------------------------------------------------------
    # Ingest (library -> managed, via hardlink; no data ever moves)
    # ------------------------------------------------------------------

    def _ingest_new_movie(
        self,
        movie: dict,
        library_folder: Path,
        mapping: MovieRootMapping,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        if not self.config.ingest.enabled:
            report.warn(f"Ingest disabled; new import left library-only: {library_folder}")
            return
        managed_folder = Path(mapping.managed_root) / library_folder.name
        self._ingest_into_folder(movie, library_folder, managed_folder, report, dry_run)

    def _ingest_into_folder(
        self,
        movie: dict,
        library_folder: Path,
        managed_folder: Path,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        if not self.config.ingest.enabled:
            report.warn(f"Ingest disabled; skipping ingest for {library_folder}")
            return
        managed_root = self._managed_root_of(managed_folder)
        mode = self.config.ingest.replacement_delete_mode
        ingested_videos: list[Path] = []
        for file_path in self._relevant_files(library_folder):
            relative = file_path.relative_to(library_folder)
            is_video = is_video_file(file_path, self.video_extensions)
            if not is_video and not matches_extras_allowlist(file_path.name, self.extras_allowlist):
                continue
            target = managed_folder / relative
            # An import carrying the same filename as the managed file it
            # replaces would otherwise be overwritten in place, bypassing
            # supersession entirely.
            if not rescue_replaced_target(
                file_path,
                target,
                managed_root=managed_root,
                mode=mode,
                kind="video" if is_video else "file",
                report=report,
                dry_run=dry_run,
            ):
                continue
            if ensure_hardlink(file_path, target, dry_run=dry_run):
                report.items_changed += 1
                report.add(
                    Action("ingest_link", "ingested into managed tree", str(file_path), str(target))
                )
                if is_video:
                    ingested_videos.append(target)
        if ingested_videos and managed_root is not None:
            self._supersede_old_videos(
                managed_folder, ingested_videos, managed_root, report, dry_run
            )
        if not dry_run:
            # A dry run created nothing, so it must not claim this mapping: the
            # next real pass would find the hint stale, read that as "known
            # before, so probably moved" and defer the ingest to the next full
            # pass instead of performing it.
            self.cache.set_folder("radarr", int(movie["id"]), managed_folder)

    def _supersede_old_videos(
        self,
        managed_folder: Path,
        keep: list[Path],
        managed_root: Path,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        keep_names = {p.name for p in keep}
        for file_path in self._relevant_files(managed_folder):
            if not is_video_file(file_path, self.video_extensions):
                continue
            if file_path.name in keep_names:
                continue  # same-named replacements were handled before the link
            supersede_managed_file(
                file_path,
                managed_root=managed_root,
                mode=self.config.ingest.replacement_delete_mode,
                kind="video",
                report=report,
                dry_run=dry_run,
            )

    # ------------------------------------------------------------------
    # Projection (managed -> library, hardlinks)
    # ------------------------------------------------------------------

    def _project(
        self,
        managed_folder: Path,
        library_folder: Path,
        arr_inode: int | None,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        desired: set[Path] = set()
        for file_path in self._relevant_files(managed_folder):
            relative = file_path.relative_to(managed_folder)
            is_video = is_video_file(file_path, self.video_extensions)
            if is_video and inode_of(file_path) == arr_inode:
                continue  # already present under Radarr's own name
            if not is_video and not matches_extras_allowlist(file_path.name, self.extras_allowlist):
                continue
            target = library_folder / relative
            desired.add(target)
            if ensure_hardlink(file_path, target, dry_run=dry_run):
                report.items_changed += 1
                report.add(Action("link", "projected to library", str(file_path), str(target)))
        self._remove_stale_projections(
            managed_folder, library_folder, desired, arr_inode, report, dry_run
        )

    def _remove_stale_projections(
        self,
        managed_folder: Path,
        library_folder: Path,
        desired: set[Path],
        arr_inode: int | None,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        managed_inodes = {
            inode
            for file_path in iter_files(managed_folder)
            if (inode := inode_of(file_path)) is not None
        }
        for file_path in self._relevant_files(library_folder):
            if file_path in desired:
                continue
            inode = inode_of(file_path)
            if inode is None or inode == arr_inode:
                continue
            if inode in managed_inodes or file_path.stat().st_nlink > 1:
                remove_file(file_path, dry_run=dry_run)
                report.items_changed += 1
                report.add(Action("unlink", "stale projection removed", None, str(file_path)))

    # ------------------------------------------------------------------
    # Prune library folders no longer referenced by Arr
    # ------------------------------------------------------------------

    def _prune_library_roots(
        self,
        movies: list[dict],
        index: InodeIndex,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        active_folders = {str(Path(movie["path"])) for movie in movies if movie.get("path")}
        for mapping in self.config.paths.movie_root_mappings:
            library_root = Path(mapping.library_root)
            if not library_root.is_dir():
                continue
            for entry in sorted(library_root.iterdir()):
                if not entry.is_dir() or str(entry) in active_folders:
                    continue
                self._prune_stale_library_folder(entry, index, report, dry_run)
            prune_empty_dirs(library_root, dry_run=dry_run)

    def _prune_stale_library_folder(
        self,
        folder: Path,
        index: InodeIndex,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        for file_path in iter_files(folder):
            stat = file_path.stat()
            is_video = is_video_file(file_path, self.video_extensions)
            if is_video and stat.st_nlink <= 1 and not index.contains(stat.st_ino):
                report.warn(
                    f"Stale library folder contains a sole-copy video, leaving as-is: {folder}"
                )
                return
        for file_path in iter_files(folder):
            remove_file(file_path, dry_run=dry_run)
            report.add(
                Action("unlink", "stale library folder content removed", None, str(file_path))
            )
        report.items_changed += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mapping_for_library_path(self, path: str) -> MovieRootMapping | None:
        if not path:
            return None
        candidate = Path(path)
        for mapping in self.config.paths.movie_root_mappings:
            if is_within(candidate, Path(mapping.library_root)):
                return mapping
        return None

    def _managed_root_of(self, managed_folder: Path) -> Path | None:
        for mapping in self.config.paths.movie_root_mappings:
            if is_within(managed_folder, Path(mapping.managed_root)):
                return Path(mapping.managed_root)
        return None

    def _reconcile_bucket(
        self,
        movie: dict,
        managed_folder: Path,
        mapping: MovieRootMapping,
        report: ReconcileReport,
        dry_run: bool,
    ) -> Path:
        """Follow a Radarr root-folder reassignment (scenario 11).

        The rules live in relocate.py so full, consistency and targeted passes
        move a managed folder on exactly the same terms.
        """
        movie_id = int(movie["id"])
        outcome = relocate_managed_folder(
            managed_folder,
            target_root=Path(mapping.managed_root),
            current_root=self._managed_root_of(managed_folder),
            label=str(movie.get("title") or movie_id),
            arr_name="Radarr",
            report=report,
            dry_run=dry_run,
            other_owners=self.cache.folder_owners("radarr", managed_folder, exclude=movie_id),
        )
        return outcome.folder

    @staticmethod
    def _managed_folder_of(source: Path, managed_folder: Path | None) -> Path:
        """The managed folder a located video belongs to — the unit that a
        bucket relocation moves.

        Normally the video's own parent. When a verified cached folder *contains*
        the video further down (multi-disc or other subfolder layouts), that
        folder is the unit instead: moving only the video's parent would leave
        the rest of the movie behind in the old bucket. A cached folder that
        does not contain the video is ignored — the video was then located via
        the inode index (the user moved it), and its own parent is the truth.
        """
        if managed_folder is not None and is_within(source, managed_folder):
            return managed_folder
        return source.parent

    def _verified_managed_folder(self, movie_id: int) -> tuple[Path | None, bool]:
        """Returns (folder, had_stale_hint).

        had_stale_hint is True when the cache had an entry for this movie but
        the folder it pointed to no longer exists — i.e. this item was known
        before, not brand new. Distinguishing the two matters because without
        an inode index (consistency scope) a moved folder cannot be
        relocated; see _reconcile_movie.
        """
        hint = self.cache.get_folder("radarr", movie_id)
        if hint is not None and hint.is_dir():
            return hint, False
        if hint is not None:
            self.cache.drop("radarr", movie_id)
            return None, True
        return None, False

    def _managed_source_for_inode(
        self,
        library_inode: int,
        managed_folder: Path | None,
        index: InodeIndex | None,
        managed_root: Path,
    ) -> tuple[Path | None, bool]:
        if managed_folder is not None:
            for file_path in self._relevant_files(managed_folder):
                if inode_of(file_path) == library_inode:
                    return file_path, False
        if index is not None:
            result = index.lookup_preferred(library_inode, root=managed_root)
            return result.path, result.ambiguous
        return None, False

    def _folder_video_inodes(self, folder: Path) -> set[int]:
        return {
            inode
            for file_path in iter_files(folder)
            if is_video_file(file_path, self.video_extensions)
            and (inode := inode_of(file_path)) is not None
        }

    @staticmethod
    def _movie_file_import_time(movie: dict) -> float | None:
        """Wall-clock time Radarr imported its current file (movieFile dateAdded)."""
        raw = (movie.get("movieFile") or {}).get("dateAdded")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    def _primary_video(self, folder: Path | None) -> Path | None:
        if folder is None or not folder.is_dir():
            return None
        videos = [
            file_path
            for file_path in iter_files(folder)
            if is_video_file(file_path, self.video_extensions)
        ]
        if not videos:
            return None
        return max(videos, key=lambda p: p.stat().st_mtime)
