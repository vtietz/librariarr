from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MovieProjectionMapping:
    managed_root: Path
    library_root: Path


@dataclass(frozen=True)
class PlannedProjectionFile:
    relative_path: str
    source_path: Path
    dest_path: Path
    kind: str


@dataclass(frozen=True)
class MovieProjectionPlan:
    movie_id: int
    title: str
    managed_folder: Path
    library_folder: Path
    mapping: MovieProjectionMapping | None
    files: list[PlannedProjectionFile] = field(default_factory=list)
    skip_reason: str | None = None


@dataclass(frozen=True)
class MappingProbeResult:
    managed_root: Path
    library_root: Path
    hardlink_capable: bool
    managed_writable: bool
    library_writable: bool
    library_temp_write_ok: bool
    library_free_bytes: int


@dataclass(frozen=True)
class ProjectedFileState:
    movie_id: int
    dest_path: str
    source_path: str
    kind: str
    managed: bool
    source_dev: int | None
    source_inode: int | None
    size: int
    mtime: float
    file_hash: str | None


@dataclass
class RootMetrics:
    """Per-root projection statistics."""

    library_root: str
    managed_root: str
    planned: int = 0
    matched: int = 0
    skipped: int = 0
    projected_files: int = 0
    unchanged_files: int = 0
    skipped_files: int = 0

    def as_dict(self) -> dict[str, int | str]:
        return {
            "library_root": self.library_root,
            "managed_root": self.managed_root,
            "planned": self.planned,
            "matched": self.matched,
            "skipped": self.skipped,
            "projected_files": self.projected_files,
            "unchanged_files": self.unchanged_files,
            "skipped_files": self.skipped_files,
        }


@dataclass
class ProjectionApplyMetrics:
    scoped_movie_count: int
    planned_movies: int = 0
    skipped_movies: int = 0
    projected_files: int = 0
    unchanged_files: int = 0
    skipped_files: int = 0
    per_root: dict[str, RootMetrics] = field(default_factory=dict)

    def record_plan(self, mapping: MovieProjectionMapping | None) -> None:
        if mapping is None:
            return
        root = self._get_root(mapping)
        root.planned += 1

    def record_skip(self, mapping: MovieProjectionMapping | None) -> None:
        if mapping is None:
            return
        root = self._get_root(mapping)
        root.skipped += 1

    def record_match(self, mapping: MovieProjectionMapping) -> None:
        root = self._get_root(mapping)
        root.matched += 1

    def record_file_projected(self, mapping: MovieProjectionMapping) -> None:
        root = self._get_root(mapping)
        root.projected_files += 1

    def record_file_unchanged(self, mapping: MovieProjectionMapping) -> None:
        root = self._get_root(mapping)
        root.unchanged_files += 1

    def record_file_skipped(self, mapping: MovieProjectionMapping) -> None:
        root = self._get_root(mapping)
        root.skipped_files += 1

    def _get_root(self, mapping: MovieProjectionMapping) -> RootMetrics:
        key = str(mapping.library_root)
        if key not in self.per_root:
            self.per_root[key] = RootMetrics(
                library_root=str(mapping.library_root),
                managed_root=str(mapping.managed_root),
            )
        return self.per_root[key]

    def per_root_list(self) -> list[dict[str, int | str]]:
        roots = sorted(self.per_root.values(), key=lambda r: r.library_root)
        return [root.as_dict() for root in roots]

    def as_dict(self) -> dict[str, int]:
        return {
            "scoped_movie_count": self.scoped_movie_count,
            "planned_movies": self.planned_movies,
            "skipped_movies": self.skipped_movies,
            "projected_files": self.projected_files,
            "unchanged_files": self.unchanged_files,
            "skipped_files": self.skipped_files,
        }
