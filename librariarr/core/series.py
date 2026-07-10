"""Sonarr reconcile: per-episode inode identity, ingest, projection, prune.

Same model as movies (see movies.py); identity is per episode file. The user
curates where the series folder lives in the nested tree; inside the series
folder the layout mirrors Sonarr's relative structure for ingested files.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..config.models import AppConfig, RootMapping
from .fsops import (
    ensure_hardlink,
    inode_of,
    is_excluded,
    is_video_file,
    is_within,
    iter_files,
    matches_extras_allowlist,
    move_to_trash,
    prune_empty_dirs,
    remove_file,
)
from .index import AdvisoryCache, InodeIndex
from .model import Action, ReconcileReport

LOG = logging.getLogger(__name__)

_PROGRESS_LOG_EVERY = 100

EPISODE_KEY_RE = re.compile(r"[Ss](\d{1,2})[EeXx](\d{2,3})")
SEASON_LIKE_RE = re.compile(r"^(season|staffel)[\s._-]*\d+$", re.IGNORECASE)


def episode_key(name: str) -> tuple[int, int] | None:
    match = EPISODE_KEY_RE.search(name)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)))


class SeriesReconciler:
    def __init__(self, config: AppConfig, sonarr, cache: AdvisoryCache) -> None:
        self.config = config
        self.sonarr = sonarr
        self.cache = cache
        self.video_extensions = config.sonarr.projection.managed_video_extensions
        self.extras_allowlist = config.sonarr.projection.managed_extras_allowlist
        self.exclude_patterns = config.paths.exclude_paths

    def _relevant_files(self, folder):
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
    ) -> tuple[list[dict], set[int]]:
        series_list = self.sonarr.get_series()
        LOG.info("Sonarr reconcile start: series=%d", len(series_list))
        tick = progress or (lambda phase, current, total: None)
        arr_inodes: set[int] = set()
        for idx, series in enumerate(series_list, start=1):
            tick("series", idx, len(series_list))
            if idx == 1 or idx % _PROGRESS_LOG_EVERY == 0 or idx == len(series_list):
                LOG.info(
                    "Sonarr progress: %d/%d current='%s'",
                    idx,
                    len(series_list),
                    series.get("title") or "<unknown>",
                )
            mapping = self._mapping_for_shadow_path(series.get("path") or "")
            if mapping is None:
                continue
            report.items_seen += 1
            report.bump("series_total")
            try:
                self._reconcile_series(series, mapping, index, arr_inodes, report, dry_run)
            except OSError as exc:
                report.errors.append(f"series '{series.get('title')}': {exc}")
        if index is not None:
            self._prune_library_roots(series_list, index, report, dry_run)
        self.cache.save()
        return series_list, arr_inodes

    # ------------------------------------------------------------------
    # Per-series reconcile
    # ------------------------------------------------------------------

    def _reconcile_series(
        self,
        series: dict,
        mapping: RootMapping,
        index: InodeIndex | None,
        arr_inodes: set[int],
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        series_id = int(series["id"])
        shadow_folder = Path(series["path"])
        episode_files = [ep for ep in self.sonarr.get_episode_files(series_id) if ep.get("path")]

        managed_folder = self._locate_managed_folder(series_id, shadow_folder, episode_files, index)
        if managed_folder is None:
            if episode_files:
                self._ingest_new_series(
                    series, shadow_folder, episode_files, mapping, report, dry_run
                )
            return

        self.cache.set_folder("sonarr", series_id, managed_folder)
        managed_inodes = self._managed_inode_map(managed_folder)
        needs_rescan = False
        for episode_file in episode_files:
            changed = self._reconcile_episode(
                series,
                episode_file,
                shadow_folder,
                managed_folder,
                managed_inodes,
                report,
                dry_run,
            )
            needs_rescan = needs_rescan or changed
        arr_inodes.update(
            inode for inode in self._episode_inodes(episode_files) if inode is not None
        )
        arr_inodes.update(
            inode
            for inode, path in managed_inodes.items()
            if is_video_file(path, self.video_extensions)
        )
        projected_new = self._project(
            series, managed_folder, shadow_folder, episode_files, report, dry_run
        )
        if (needs_rescan or projected_new) and not dry_run:
            self.sonarr.refresh_series(series_id)

    def _reconcile_episode(
        self,
        series: dict,
        episode_file: dict,
        shadow_folder: Path,
        managed_folder: Path,
        managed_inodes: dict[int, Path],
        report: ReconcileReport,
        dry_run: bool,
    ) -> bool:
        shadow_path = Path(episode_file["path"])
        relative = episode_file.get("relativePath") or shadow_path.name
        shadow_inode = inode_of(shadow_path)
        report.bump("episodes_total")

        if shadow_inode is None:
            return self._restore_missing_episode(shadow_path, managed_folder, report, dry_run)
        if shadow_inode in managed_inodes:
            report.bump("episodes_in_sync")
            return False  # identity holds

        key = episode_key(shadow_path.name)
        managed_same_episode = self._managed_files_for_episode(managed_folder, key)
        newest_managed = max(managed_same_episode, key=lambda p: p.stat().st_mtime, default=None)
        if (
            newest_managed is not None
            and newest_managed.stat().st_mtime > shadow_path.stat().st_mtime
        ):
            report.warn(
                f"Managed episode newer than Sonarr's file for '{series.get('title')}' "
                f"{shadow_path.name}; relinking (user replacement wins)"
            )
            if ensure_hardlink(newest_managed, shadow_path, dry_run=dry_run):
                report.items_changed += 1
                report.add(
                    Action("relink", "user replacement wins", str(newest_managed), str(shadow_path))
                )
                return True
            return False

        return self._ingest_episode(
            shadow_path, relative, managed_folder, managed_same_episode, report, dry_run
        )

    def _restore_missing_episode(
        self,
        shadow_path: Path,
        managed_folder: Path,
        report: ReconcileReport,
        dry_run: bool,
    ) -> bool:
        for file_path in self._relevant_files(managed_folder):
            if file_path.name == shadow_path.name:
                if ensure_hardlink(file_path, shadow_path, dry_run=dry_run):
                    report.items_changed += 1
                    report.add(
                        Action(
                            "relink",
                            "restored missing shadow episode",
                            str(file_path),
                            str(shadow_path),
                        )
                    )
                    return True
                return False
        report.warn(f"Sonarr file missing on disk and no managed source: {shadow_path}")
        return False

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def _ingest_new_series(
        self,
        series: dict,
        shadow_folder: Path,
        episode_files: list[dict],
        mapping: RootMapping,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        if not self.config.ingest.enabled:
            report.warn(f"Ingest disabled; new series left shadow-only: {shadow_folder}")
            return
        managed_folder = Path(mapping.managed_root) / shadow_folder.name
        changed = False
        for file_path in self._relevant_files(shadow_folder):
            is_video = is_video_file(file_path, self.video_extensions)
            if not is_video and not matches_extras_allowlist(file_path.name, self.extras_allowlist):
                continue
            target = managed_folder / file_path.relative_to(shadow_folder)
            if ensure_hardlink(file_path, target, dry_run=dry_run):
                changed = True
                report.items_changed += 1
                report.add(
                    Action(
                        "ingest_link", "ingested new series content", str(file_path), str(target)
                    )
                )
        if changed or managed_folder.is_dir():
            self.cache.set_folder("sonarr", int(series["id"]), managed_folder)

    def _ingest_episode(
        self,
        shadow_path: Path,
        relative: str,
        managed_folder: Path,
        superseded: list[Path],
        report: ReconcileReport,
        dry_run: bool,
    ) -> bool:
        if not self.config.ingest.enabled:
            report.warn(f"Ingest disabled; skipping episode ingest: {shadow_path}")
            return False
        target = managed_folder / relative
        if not ensure_hardlink(shadow_path, target, dry_run=dry_run):
            return False
        report.items_changed += 1
        report.add(
            Action(
                "ingest_link", "ingested episode into managed tree", str(shadow_path), str(target)
            )
        )
        managed_root = self._managed_root_of(managed_folder)
        for old_file in superseded:
            if old_file == target:
                continue
            if self.config.ingest.replacement_delete_mode == "hard":
                remove_file(old_file, dry_run=dry_run)
                report.add(
                    Action("unlink", "superseded managed episode removed", str(old_file), None)
                )
            elif managed_root is not None:
                destination = move_to_trash(old_file, managed_root, dry_run=dry_run)
                report.add(
                    Action(
                        "trash",
                        "superseded managed episode quarantined",
                        str(old_file),
                        str(destination),
                    )
                )
            report.items_changed += 1
        return True

    # ------------------------------------------------------------------
    # Projection
    # ------------------------------------------------------------------

    def _project(
        self,
        series: dict,
        managed_folder: Path,
        shadow_folder: Path,
        episode_files: list[dict],
        report: ReconcileReport,
        dry_run: bool,
    ) -> bool:
        arr_paths = {Path(ep["path"]) for ep in episode_files}
        arr_inodes = {ino for ino in self._episode_inodes(episode_files) if ino is not None}
        desired: set[Path] = set(arr_paths)
        projected_new = False
        for file_path in self._relevant_files(managed_folder):
            is_video = is_video_file(file_path, self.video_extensions)
            if is_video and inode_of(file_path) in arr_inodes:
                continue  # already present under Sonarr's own name
            if not is_video and not matches_extras_allowlist(file_path.name, self.extras_allowlist):
                continue
            target = shadow_folder / file_path.relative_to(managed_folder)
            desired.add(target)
            if ensure_hardlink(file_path, target, dry_run=dry_run):
                report.items_changed += 1
                report.add(Action("link", "projected to shadow", str(file_path), str(target)))
                projected_new = projected_new or is_video
        self._remove_stale_shadow_files(managed_folder, shadow_folder, desired, report, dry_run)
        return projected_new

    def _remove_stale_shadow_files(
        self,
        managed_folder: Path,
        shadow_folder: Path,
        desired: set[Path],
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        managed_inodes = set(self._managed_inode_map(managed_folder))
        for file_path in self._relevant_files(shadow_folder):
            if file_path in desired:
                continue
            inode = inode_of(file_path)
            if inode is None:
                continue
            if inode in managed_inodes or file_path.stat().st_nlink > 1:
                remove_file(file_path, dry_run=dry_run)
                report.items_changed += 1
                report.add(Action("unlink", "stale shadow file removed", None, str(file_path)))

    # ------------------------------------------------------------------
    # Prune shadow roots
    # ------------------------------------------------------------------

    def _prune_library_roots(
        self,
        series_list: list[dict],
        index: InodeIndex,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        active = {str(Path(s["path"])) for s in series_list if s.get("path")}
        for mapping in self.config.paths.series_root_mappings:
            library_root = Path(mapping.library_root)
            if not library_root.is_dir():
                continue
            for entry in sorted(library_root.iterdir()):
                if not entry.is_dir() or str(entry) in active:
                    continue
                self._prune_stale_shadow_folder(entry, index, report, dry_run)
            prune_empty_dirs(library_root, dry_run=dry_run)

    def _prune_stale_shadow_folder(
        self,
        folder: Path,
        index: InodeIndex,
        report: ReconcileReport,
        dry_run: bool,
    ) -> None:
        for file_path in iter_files(folder):
            stat = file_path.stat()
            if (
                is_video_file(file_path, self.video_extensions)
                and stat.st_nlink <= 1
                and not index.contains(stat.st_ino)
            ):
                report.warn(
                    f"Stale shadow folder contains a sole-copy video, leaving as-is: {folder}"
                )
                return
        for file_path in iter_files(folder):
            remove_file(file_path, dry_run=dry_run)
            report.add(
                Action("unlink", "stale shadow folder content removed", None, str(file_path))
            )
        report.items_changed += 1

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mapping_for_shadow_path(self, path: str) -> RootMapping | None:
        if not path:
            return None
        candidate = Path(path)
        for mapping in self.config.paths.series_root_mappings:
            if is_within(candidate, Path(mapping.library_root)):
                return mapping
        return None

    def _managed_root_of(self, managed_folder: Path) -> Path | None:
        for mapping in self.config.paths.series_root_mappings:
            if is_within(managed_folder, Path(mapping.managed_root)):
                return Path(mapping.managed_root)
        return None

    def _locate_managed_folder(
        self,
        series_id: int,
        shadow_folder: Path,
        episode_files: list[dict],
        index: InodeIndex | None,
    ) -> Path | None:
        hint = self.cache.get_folder("sonarr", series_id)
        if hint is not None and hint.is_dir():
            return hint
        if hint is not None:
            self.cache.drop("sonarr", series_id)
        if index is None:
            return None
        for episode_file in episode_files:
            inode = inode_of(Path(episode_file["path"]))
            if inode is None:
                continue
            managed_path = index.lookup(inode)
            if managed_path is None:
                continue
            return self._derive_series_folder(managed_path, episode_file.get("relativePath") or "")
        return None

    @staticmethod
    def _derive_series_folder(managed_episode: Path, relative_path: str) -> Path:
        relative = Path(relative_path)
        candidate = managed_episode
        for part in reversed(relative.parts):
            if candidate.name == part:
                candidate = candidate.parent
            else:
                break
        if candidate != managed_episode:
            return candidate
        parent = managed_episode.parent
        if SEASON_LIKE_RE.match(parent.name):
            return parent.parent
        return parent

    def _managed_inode_map(self, managed_folder: Path) -> dict[int, Path]:
        return {
            inode: file_path
            for file_path in iter_files(managed_folder)
            if (inode := inode_of(file_path)) is not None
        }

    def _managed_files_for_episode(
        self, managed_folder: Path, key: tuple[int, int] | None
    ) -> list[Path]:
        if key is None:
            return []
        return [
            file_path
            for file_path in iter_files(managed_folder)
            if is_video_file(file_path, self.video_extensions)
            and episode_key(file_path.name) == key
        ]

    @staticmethod
    def _episode_inodes(episode_files: list[dict]) -> set[int | None]:
        return {inode_of(Path(ep["path"])) for ep in episode_files}
