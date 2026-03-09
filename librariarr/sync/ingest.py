from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path

from ..config import IngestConfig

INGEST_LOCK_SUFFIX = ".librariarr-ingest.lock"
INGEST_STATE_FILE = ".librariarr-ingest-state.json"
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

    def run(self) -> int:
        ingested_count = 0
        for shadow_root in self.shadow_roots:
            if not shadow_root.exists():
                continue

            for candidate in sorted(shadow_root.iterdir()):
                if not self._is_ingest_candidate(candidate):
                    continue

                if not self._is_quiescent_folder(candidate):
                    self.log.debug("Skipping ingest candidate still being written: %s", candidate)
                    continue

                lock_path = self._ingest_lock_path(candidate)
                if not self._acquire_ingest_lock(lock_path):
                    continue

                try:
                    if self._ingest_candidate_folder(candidate, shadow_root):
                        ingested_count += 1
                finally:
                    self._release_ingest_lock(lock_path)

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
        min_age_seconds = self.config.min_age_seconds
        if min_age_seconds <= 0:
            return True

        latest_mtime = self._latest_tree_mtime(folder)
        if latest_mtime is None:
            return False
        return (time.time() - latest_mtime) >= min_age_seconds

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

        nested_root = self._select_ingest_nested_root(shadow_root, relative)
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

    def _select_ingest_nested_root(self, shadow_root: Path, relative: Path) -> Path | None:
        candidates = self.shadow_to_nested_roots.get(shadow_root, [])
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        selector = self.config.selector
        if selector == "largest_free":
            return max(candidates, key=self._free_bytes_for_root)

        if selector == "round_robin":
            return self._select_round_robin_nested_root(shadow_root, candidates)

        if selector == "explicit_map":
            explicit = self._select_explicit_map_nested_root(relative, candidates)
            if explicit is not None:
                return explicit

        return candidates[0]

    def _free_bytes_for_root(self, path: Path) -> int:
        try:
            return shutil.disk_usage(path).free
        except OSError:
            return -1

    def _select_round_robin_nested_root(self, shadow_root: Path, candidates: list[Path]) -> Path:
        state = self._read_round_robin_state(shadow_root)
        index = int(state.get("round_robin_index", 0)) % len(candidates)
        selected = candidates[index]
        state["round_robin_index"] = (index + 1) % len(candidates)
        self._write_round_robin_state(shadow_root, state)
        return selected

    def _ingest_state_file(self, shadow_root: Path) -> Path:
        return shadow_root / INGEST_STATE_FILE

    def _read_round_robin_state(self, shadow_root: Path) -> dict[str, int]:
        state_path = self._ingest_state_file(shadow_root)
        if not state_path.exists():
            return {}

        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_round_robin_state(self, shadow_root: Path, state: dict[str, int]) -> None:
        state_path = self._ingest_state_file(shadow_root)
        try:
            state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            self.log.warning("Failed to persist ingest round-robin state: %s", state_path)

    def _select_explicit_map_nested_root(
        self,
        relative: Path,
        candidates: list[Path],
    ) -> Path | None:
        relative_text = str(relative).replace("\\", "/").strip("/")
        for rule in self.config.explicit_map:
            prefix = rule.shadow_prefix.strip("/")
            if not prefix:
                continue
            if relative_text == prefix or relative_text.startswith(f"{prefix}/"):
                mapped = Path(rule.nested_root)
                if mapped in candidates:
                    return mapped
        return None

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
