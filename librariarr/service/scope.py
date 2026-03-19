from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..sync import discover_series_folders


class ServiceScopeMixin:
    def _resolve_reconcile_scope(
        self,
        affected_paths: set[Path] | None,
        known_folders: dict[Path, Path] | None,
        discover: Callable[[Path, set[str], list[str] | None], set[Path]],
    ) -> tuple[dict[Path, Path], dict[Path, Path], set[Path], bool]:
        if affected_paths is None or not affected_paths or known_folders is None:
            found_folders = self._all_folders(discover)
            return found_folders, dict(found_folders), set(found_folders.keys()), False

        nested_affected_paths = {
            path for path in affected_paths if self._mapping_for_nested_path(path) is not None
        }
        if not nested_affected_paths:
            return {}, dict(known_folders), set(), True

        scan_scopes = self._collect_incremental_scan_scopes(nested_affected_paths)
        if not scan_scopes:
            found_folders = self._all_folders(discover)
            return found_folders, found_folders, set(found_folders.keys()), False

        known_discovered_folders = dict(known_folders)
        affected_targets: set[Path] = set()

        for scan_root, shadow_root in scan_scopes:
            removed_in_scope = [
                folder
                for folder in known_discovered_folders
                if self._path_is_equal_or_child(folder, scan_root)
            ]
            for folder in removed_in_scope:
                known_discovered_folders.pop(folder, None)
                affected_targets.add(folder)

            for folder in discover(scan_root, self.video_exts, self.scan_exclude_paths):
                known_discovered_folders[folder] = shadow_root
                affected_targets.add(folder)

        scoped_folders = {
            folder: known_discovered_folders[folder]
            for folder in affected_targets
            if folder in known_discovered_folders
        }
        return scoped_folders, known_discovered_folders, affected_targets, True

    def _collect_incremental_scan_scopes(
        self,
        affected_paths: set[Path],
    ) -> list[tuple[Path, Path]]:
        scopes: list[tuple[Path, Path]] = []
        seen: set[tuple[Path, Path]] = set()

        for changed_path in affected_paths:
            mapping = self._mapping_for_nested_path(changed_path)
            if mapping is None:
                return []

            nested_root, shadow_root = mapping
            scan_root = self._resolve_incremental_scan_root(changed_path, nested_root)
            if scan_root is None:
                return []

            scope = (scan_root, shadow_root)
            if scope in seen:
                continue
            seen.add(scope)
            scopes.append(scope)

        return scopes

    def _mapping_for_nested_path(self, path: Path) -> tuple[Path, Path] | None:
        for nested_root, shadow_root in sorted(
            self.root_mappings,
            key=lambda pair: (-len(pair[0].parts), str(pair[0])),
        ):
            if self._path_is_equal_or_child(path, nested_root):
                return nested_root, shadow_root
        return None

    def _resolve_incremental_scan_root(self, changed_path: Path, nested_root: Path) -> Path | None:
        if changed_path.exists() and changed_path.is_file():
            current = changed_path.parent
        elif changed_path.exists():
            current = changed_path
        else:
            current = changed_path.parent

        while self._path_is_equal_or_child(current, nested_root):
            if current.exists():
                return current
            if current == nested_root:
                break
            current = current.parent

        if nested_root.exists():
            return nested_root
        return None

    def _path_is_equal_or_child(self, path: Path, parent: Path) -> bool:
        if path == parent:
            return True
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False

    def _all_series_folders(self) -> dict[Path, Path]:
        return self._all_folders(discover_series_folders)

    def _all_folders(
        self,
        discover: Callable[[Path, set[str], list[str] | None], set[Path]],
    ) -> dict[Path, Path]:
        all_folders: dict[Path, Path] = {}
        sorted_mappings = sorted(
            self.root_mappings,
            key=lambda pair: (-len(pair[0].parts), str(pair[0])),
        )
        for nested_root, shadow_root in sorted_mappings:
            for folder in discover(nested_root, self.video_exts, self.scan_exclude_paths):
                all_folders.setdefault(folder, shadow_root)
        return all_folders

    def _is_sonarr_root_available(self, shadow_root: Path) -> bool:
        normalized = self._normalize_arr_root_path(str(shadow_root))
        return normalized not in self._sonarr_missing_shadow_roots
