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
class ProjectionApplyMetrics:
    scoped_movie_count: int
    planned_movies: int = 0
    skipped_movies: int = 0
    projected_files: int = 0
    unchanged_files: int = 0
    skipped_files: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "scoped_movie_count": self.scoped_movie_count,
            "planned_movies": self.planned_movies,
            "skipped_movies": self.skipped_movies,
            "projected_files": self.projected_files,
            "unchanged_files": self.unchanged_files,
            "skipped_files": self.skipped_files,
        }
