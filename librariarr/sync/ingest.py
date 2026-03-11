from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path

from ..config import IngestConfig

INGEST_LOCK_SUFFIX = ".librariarr-ingest.lock"
INGEST_LOCK_STALE_SECONDS = 3600


class ShadowIngestor:
    def __init__(
        self,
        config: IngestConfig,
        video_exts: set[str],
        shadow_roots: list[Path],
        shadow_to_nested_roots: dict[Path, list[Path]],
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self.video_exts = video_exts
        self.shadow_roots = shadow_roots
        self.shadow_to_nested_roots = shadow_to_nested_roots
        self.log = logger or logging.getLogger(__name__)
        self.last_pending_quiescent_count = 0

    def run(self) -> int:
        ingested_count = 0
        pending_quiescent_count = 0
        for shadow_root in self.shadow_roots:
            if not shadow_root.exists():
                continue

            for candidate in sorted(shadow_root.iterdir()):
                if not self._is_ingest_candidate(candidate):
                    continue

                quiescent_remaining = self._quiescent_remaining_seconds(candidate)
                if quiescent_remaining > 0:
                    pending_quiescent_count += 1
                    self.log.info(
                        "Deferring ingest candidate until stable: %s "
                        "(remaining_seconds=%s min_age_seconds=%s)",
                        candidate,
                        quiescent_remaining,
                        self.config.min_age_seconds,
                    )
                    continue

                lock_path = self._ingest_lock_path(candidate)
                if not self._acquire_ingest_lock(lock_path):
                    continue

                try:
                    if self._ingest_candidate_folder(candidate, shadow_root):
                        ingested_count += 1
                finally:
                    self._release_ingest_lock(lock_path)

        self.last_pending_quiescent_count = pending_quiescent_count
        return ingested_count

    def _is_ingest_candidate(self, path: Path) -> bool:
        if path.name.startswith("."):
            return False
        if not path.exists() or not path.is_dir() or path.is_symlink():
            return False
        if not self._directory_contains_video(path):
            return False
        return not self._contains_partial_files(path)

    def _directory_contains_video(self, path: Path) -> bool:
        for _, _, files in os.walk(path):
            if any(Path(filename).suffix.lower() in self.video_exts for filename in files):
                return True
        return False

    def _contains_partial_files(self, path: Path) -> bool:
        temp_suffixes = {".part", ".partial", ".tmp", ".!qb"}
        for _, _, files in os.walk(path):
            for filename in files:
                lower = filename.lower()
                if any(lower.endswith(suffix) for suffix in temp_suffixes):
                    return True
        return False

    def _is_quiescent_folder(self, folder: Path) -> bool:
        return self._quiescent_remaining_seconds(folder) == 0

    def _quiescent_remaining_seconds(self, folder: Path) -> int:
        min_age_seconds = self.config.min_age_seconds
        if min_age_seconds <= 0:
            return 0

        latest_mtime = self._latest_tree_mtime(folder)
        if latest_mtime is None:
            return min_age_seconds

        elapsed_seconds = max(0.0, time.time() - latest_mtime)
        remaining = int(max(0.0, min_age_seconds - elapsed_seconds))
        if remaining == 0 and elapsed_seconds < min_age_seconds:
            return 1
        return remaining

    def _latest_tree_mtime(self, folder: Path) -> float | None:
        latest: float | None = None
        for current, dirs, files in os.walk(folder):
            base = Path(current)
            paths = [
                base,
                *(base / name for name in dirs),
                *(base / name for name in files),
            ]
            for path in paths:
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                latest = mtime if latest is None else max(latest, mtime)
        return latest

    def _ingest_lock_path(self, folder: Path) -> Path:
        return folder.parent / f".{folder.name}{INGEST_LOCK_SUFFIX}"

    def _acquire_ingest_lock(self, lock_path: Path) -> bool:
        for _ in range(2):
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                fd = os.open(str(lock_path), flags)
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(str(time.time()))
                return True
            except FileExistsError:
                if not self._clear_stale_lock(lock_path):
                    return False
            except OSError:
                return False
        return False

    def _clear_stale_lock(self, lock_path: Path) -> bool:
        try:
            age_seconds = time.time() - lock_path.stat().st_mtime
        except OSError:
            return False

        if age_seconds < INGEST_LOCK_STALE_SECONDS:
            return False

        try:
            lock_path.unlink(missing_ok=True)
            self.log.warning("Removed stale ingest lock: %s", lock_path)
            return True
        except OSError:
            return False

    def _release_ingest_lock(self, lock_path: Path) -> None:
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            self.log.warning("Failed to remove ingest lock: %s", lock_path)

    def _ingest_candidate_folder(self, source: Path, shadow_root: Path) -> bool:
        try:
            relative = source.relative_to(shadow_root)
        except ValueError:
            self.log.warning("Skipping ingest candidate outside shadow root: %s", source)
            return False

        nested_root = self._select_ingest_nested_root(shadow_root)
        if nested_root is None:
            self.log.warning("No nested root target available for ingest candidate: %s", source)
            return False

        destination = self._resolve_ingest_destination(nested_root / relative)
        if destination is None:
            self.log.info("Skipped ingest candidate due to collision policy: %s", source)
            return False

        try:
            self._move_folder(source, destination)
            source.symlink_to(destination, target_is_directory=True)
            self.log.info("Ingested folder: %s -> %s", source, destination)
            return True
        except Exception:
            self.log.exception("Failed ingest for candidate: %s", source)
            self._quarantine_failed_ingest(source, shadow_root)
            return False

    def _select_ingest_nested_root(self, shadow_root: Path) -> Path | None:
        candidates = self.shadow_to_nested_roots.get(shadow_root, [])
        if len(candidates) != 1:
            return None
        return candidates[0]

    def _resolve_ingest_destination(self, destination: Path) -> Path | None:
        if not destination.exists() and not destination.is_symlink():
            return destination

        if self.config.collision_policy == "skip":
            return None

        parent = destination.parent
        name = destination.name
        counter = 2
        candidate = parent / f"{name} [ingest-{counter}]"
        while candidate.exists() or candidate.is_symlink():
            counter += 1
            candidate = parent / f"{name} [ingest-{counter}]"
        return candidate

    def _move_folder(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)

        same_device = False
        try:
            same_device = source.stat().st_dev == destination.parent.stat().st_dev
        except OSError:
            same_device = False

        if same_device:
            source.rename(destination)
            return

        shutil.copytree(source, destination, symlinks=True)
        self._verify_copied_tree(source, destination)
        shutil.rmtree(source)

    def _verify_copied_tree(self, source: Path, destination: Path) -> None:
        src_sig = self._tree_signature(source)
        dst_sig = self._tree_signature(destination)
        if src_sig != dst_sig:
            raise OSError(f"Copied tree verification failed: src={src_sig} dst={dst_sig}")

    def _tree_signature(self, root: Path) -> tuple[int, int]:
        file_count = 0
        total_size = 0
        for current, _, files in os.walk(root):
            base = Path(current)
            for name in files:
                file_count += 1
                try:
                    total_size += (base / name).stat().st_size
                except OSError:
                    continue
        return file_count, total_size

    def _quarantine_failed_ingest(self, source: Path, shadow_root: Path) -> None:
        quarantine_root = self.config.quarantine_root.strip()
        if not quarantine_root:
            return
        if not source.exists() or not source.is_dir() or source.is_symlink():
            return

        timestamp = int(time.time())
        try:
            relative = source.relative_to(shadow_root)
        except ValueError:
            relative = Path(source.name)

        base_destination = Path(quarantine_root) / shadow_root.name / relative.parent
        destination = base_destination / f"{relative.name}.{timestamp}"
        counter = 2
        while destination.exists():
            destination = base_destination / f"{relative.name}.{timestamp}.{counter}"
            counter += 1

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(source), str(destination))
            self.log.error("Moved failed ingest candidate to quarantine: %s", destination)
        except OSError:
            self.log.exception("Failed to quarantine ingest candidate: %s", source)
