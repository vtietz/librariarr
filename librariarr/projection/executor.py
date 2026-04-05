from __future__ import annotations

import errno
import logging
import os
from pathlib import Path

from .models import (
    MappingProbeResult,
    MovieProjectionPlan,
    ProjectedFileState,
    ProjectionApplyMetrics,
)
from .provenance import ProjectionStateStore

LOG = logging.getLogger(__name__)


class MovieProjectionExecutor:
    def __init__(
        self,
        *,
        state_store: ProjectionStateStore,
        preserve_unknown_files: bool,
    ) -> None:
        self.state_store = state_store
        self.preserve_unknown_files = preserve_unknown_files

    def apply(
        self,
        *,
        plans: list[MovieProjectionPlan],
        probes: dict[tuple[str, str], MappingProbeResult],
        scoped_movie_count: int,
    ) -> ProjectionApplyMetrics:
        metrics = ProjectionApplyMetrics(scoped_movie_count=scoped_movie_count)

        for plan in plans:
            metrics.planned_movies += 1
            if plan.skip_reason is not None or plan.mapping is None:
                metrics.skipped_movies += 1
                continue

            probe_key = (str(plan.mapping.managed_root), str(plan.mapping.library_root))
            probe = probes.get(probe_key)
            if not self._is_mapping_actionable(probe):
                metrics.skipped_movies += 1
                continue

            managed_dest_paths = self.state_store.get_managed_paths_for_movie(plan.movie_id)
            upserts: list[ProjectedFileState] = []

            for planned_file in plan.files:
                result = self._apply_single_file(
                    movie_id=plan.movie_id,
                    source_path=planned_file.source_path,
                    dest_path=planned_file.dest_path,
                    kind=planned_file.kind,
                    managed_dest_paths=managed_dest_paths,
                )
                if result is None:
                    metrics.skipped_files += 1
                    continue
                if result == "unchanged":
                    metrics.unchanged_files += 1
                    continue

                upserts.append(result)
                metrics.projected_files += 1

            self.state_store.upsert_projected_files(upserts)

        return metrics

    def _is_mapping_actionable(self, probe: MappingProbeResult | None) -> bool:
        if probe is None:
            return False
        if not probe.hardlink_capable:
            return False
        if not probe.managed_writable:
            return False
        if not probe.library_writable:
            return False
        if not probe.library_temp_write_ok:
            return False
        return True

    def _apply_single_file(
        self,
        *,
        movie_id: int,
        source_path: Path,
        dest_path: Path,
        kind: str,
        managed_dest_paths: set[str],
    ) -> ProjectedFileState | str | None:
        if not source_path.exists() or not source_path.is_file():
            return None

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        managed_dest = str(dest_path) in managed_dest_paths

        if dest_path.exists() or dest_path.is_symlink():
            if _is_same_file(source_path, dest_path):
                return "unchanged"
            if not managed_dest and self.preserve_unknown_files:
                return None
            # Rename before unlinking so we can restore on hardlink failure
            backup_path = dest_path.with_suffix(dest_path.suffix + ".librariarr-tmp")
            try:
                dest_path.rename(backup_path)
            except OSError as exc:
                LOG.warning(
                    "Cannot rename existing dest for safe replacement, skipping: dest=%s error=%s",
                    dest_path,
                    exc,
                )
                return None

            if not _hardlink_file(source_path, dest_path):
                # Hardlink failed — restore the backup so we don't lose the file
                try:
                    backup_path.rename(dest_path)
                    LOG.warning(
                        "Hardlink failed, restored previous file: dest=%s source=%s",
                        dest_path,
                        source_path,
                    )
                except OSError as restore_exc:
                    LOG.error(
                        "Hardlink failed AND could not restore backup: dest=%s backup=%s error=%s",
                        dest_path,
                        backup_path,
                        restore_exc,
                    )
                return None

            # Hardlink succeeded — clean up the backup
            backup_path.unlink(missing_ok=True)
        else:
            if not _hardlink_file(source_path, dest_path):
                return None

        source_stat = source_path.stat()
        return ProjectedFileState(
            movie_id=movie_id,
            dest_path=str(dest_path),
            source_path=str(source_path),
            kind=kind,
            managed=True,
            source_dev=int(source_stat.st_dev),
            source_inode=int(source_stat.st_ino),
            size=int(source_stat.st_size),
            mtime=float(source_stat.st_mtime),
            file_hash=None,
        )

    def _remove_existing_dest(self, dest_path: Path) -> None:
        if dest_path.is_symlink() or dest_path.is_file():
            dest_path.unlink(missing_ok=True)
            return
        if dest_path.exists() and dest_path.is_dir():
            raise IsADirectoryError(f"Expected file destination, found directory: {dest_path}")


def _is_same_file(source_path: Path, dest_path: Path) -> bool:
    try:
        return source_path.samefile(dest_path)
    except OSError:
        return False


def _hardlink_file(source_path: Path, dest_path: Path) -> bool:
    try:
        os.link(source_path, dest_path)
        return True
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            LOG.warning(
                "Cross-device hardlink failed (source and dest are on different filesystems): "
                "source=%s dest=%s — check your volume/mount layout",
                source_path,
                dest_path,
            )
            return False
        if exc.errno in {errno.EPERM, errno.EACCES}:
            LOG.warning(
                "Hardlink failed (permission denied): source=%s dest=%s — "
                "check file/directory ownership and permissions",
                source_path,
                dest_path,
            )
            return False
        raise
