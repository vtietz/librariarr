from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from .models import ProjectedFileState

LOG = logging.getLogger(__name__)

_MAINTENANCE_INTERVAL = 86400  # 24 hours


class ProjectionStateStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._last_maintenance = 0.0
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._connect() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS projected_files (
                        movie_id INTEGER NOT NULL,
                        dest_path TEXT NOT NULL,
                        source_path TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        managed INTEGER NOT NULL,
                        source_dev INTEGER,
                        source_inode INTEGER,
                        size INTEGER NOT NULL,
                        mtime REAL NOT NULL,
                        file_hash TEXT,
                        updated_at REAL NOT NULL DEFAULT (strftime('%s', 'now')),
                        PRIMARY KEY (movie_id, dest_path)
                    );

                    CREATE INDEX IF NOT EXISTS idx_projected_files_movie_id
                        ON projected_files (movie_id);

                    CREATE TABLE IF NOT EXISTS movie_managed_folders (
                        movie_id INTEGER NOT NULL PRIMARY KEY,
                        managed_folder TEXT NOT NULL,
                        updated_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
                    );

                    CREATE TABLE IF NOT EXISTS series_managed_folders (
                        series_id INTEGER NOT NULL PRIMARY KEY,
                        managed_folder TEXT NOT NULL,
                        updated_at REAL NOT NULL DEFAULT (strftime('%s', 'now'))
                    );
                    """
                )

    def get_managed_paths_for_movie(self, movie_id: int) -> set[str]:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    SELECT dest_path
                    FROM projected_files
                    WHERE movie_id = ? AND managed = 1
                    """,
                    (movie_id,),
                )
                return {str(row[0]) for row in cursor.fetchall()}

    def get_managed_entries_for_movie(self, movie_id: int) -> list[tuple[str, str]]:
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    SELECT dest_path, source_path
                    FROM projected_files
                    WHERE movie_id = ? AND managed = 1
                    """,
                    (movie_id,),
                )
                return [(str(row[0]), str(row[1])) for row in cursor.fetchall()]

    def list_managed_projected_rows(
        self,
        *,
        movie_ids: set[int] | None = None,
    ) -> list[tuple[int, str, str, int | None, int | None]]:
        """Return managed provenance rows as (id, dest, source, dev, inode)."""
        with self._lock:
            with self._connect() as connection:
                if movie_ids:
                    placeholders = ",".join("?" for _ in movie_ids)
                    cursor = connection.execute(
                        f"""
                        SELECT movie_id, dest_path, source_path, source_dev, source_inode
                        FROM projected_files
                        WHERE managed = 1 AND movie_id IN ({placeholders})
                        ORDER BY movie_id, dest_path
                        """,
                        tuple(sorted(movie_ids)),
                    )
                else:
                    cursor = connection.execute(
                        """
                        SELECT movie_id, dest_path, source_path, source_dev, source_inode
                        FROM projected_files
                        WHERE managed = 1
                        ORDER BY movie_id, dest_path
                        """
                    )
                return [
                    (int(row[0]), str(row[1]), str(row[2]), row[3], row[4])
                    for row in cursor.fetchall()
                ]

    def delete_projected_file_row(self, movie_id: int, dest_path: str) -> None:
        """Delete a single projected_files provenance row."""
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM projected_files WHERE movie_id = ? AND dest_path = ?",
                    (movie_id, dest_path),
                )

    def get_managed_folders_by_movie_ids(self) -> dict[int, Path]:
        """Return a mapping of movie_id → managed folder from the explicit mapping table."""
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    "SELECT movie_id, managed_folder FROM movie_managed_folders"
                )
                return {int(row[0]): Path(row[1]) for row in cursor.fetchall() if row[1]}

    def set_managed_folder(self, movie_id: int, managed_folder: Path) -> None:
        """Store the managed folder for a movie."""
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO movie_managed_folders (movie_id, managed_folder, updated_at)
                    VALUES (?, ?, strftime('%s', 'now'))
                    ON CONFLICT(movie_id) DO UPDATE SET
                        managed_folder = excluded.managed_folder,
                        updated_at = excluded.updated_at
                    """,
                    (movie_id, str(managed_folder)),
                )

    def set_managed_folders_bulk(self, mappings: list[tuple[int, Path]]) -> None:
        """Store managed folders for multiple movies."""
        if not mappings:
            return
        with self._lock:
            with self._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO movie_managed_folders (movie_id, managed_folder, updated_at)
                    VALUES (?, ?, strftime('%s', 'now'))
                    ON CONFLICT(movie_id) DO UPDATE SET
                        managed_folder = excluded.managed_folder,
                        updated_at = excluded.updated_at
                    """,
                    [(movie_id, str(folder)) for movie_id, folder in mappings],
                )

    def remove_managed_folder(self, movie_id: int) -> None:
        """Remove the managed folder mapping for a movie."""
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM movie_managed_folders WHERE movie_id = ?",
                    (movie_id,),
                )

    def get_managed_folders_by_series_ids(self) -> dict[int, Path]:
        """Return a mapping of series_id → managed folder from explicit mapping table."""
        with self._lock:
            with self._connect() as connection:
                cursor = connection.execute(
                    "SELECT series_id, managed_folder FROM series_managed_folders"
                )
                return {int(row[0]): Path(row[1]) for row in cursor.fetchall() if row[1]}

    def set_managed_series_folder(self, series_id: int, managed_folder: Path) -> None:
        """Store the managed folder for a series."""
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO series_managed_folders (series_id, managed_folder, updated_at)
                    VALUES (?, ?, strftime('%s', 'now'))
                    ON CONFLICT(series_id) DO UPDATE SET
                        managed_folder = excluded.managed_folder,
                        updated_at = excluded.updated_at
                    """,
                    (series_id, str(managed_folder)),
                )

    def set_managed_series_folders_bulk(self, mappings: list[tuple[int, Path]]) -> None:
        """Store managed folders for multiple series."""
        if not mappings:
            return
        with self._lock:
            with self._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO series_managed_folders (series_id, managed_folder, updated_at)
                    VALUES (?, ?, strftime('%s', 'now'))
                    ON CONFLICT(series_id) DO UPDATE SET
                        managed_folder = excluded.managed_folder,
                        updated_at = excluded.updated_at
                    """,
                    [(series_id, str(folder)) for series_id, folder in mappings],
                )

    def upsert_projected_files(self, records: list[ProjectedFileState]) -> None:
        if not records:
            return
        with self._lock:
            with self._connect() as connection:
                connection.executemany(
                    """
                    INSERT INTO projected_files (
                        movie_id,
                        dest_path,
                        source_path,
                        kind,
                        managed,
                        source_dev,
                        source_inode,
                        size,
                        mtime,
                        file_hash,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                    ON CONFLICT(movie_id, dest_path) DO UPDATE SET
                        source_path = excluded.source_path,
                        kind = excluded.kind,
                        managed = excluded.managed,
                        source_dev = excluded.source_dev,
                        source_inode = excluded.source_inode,
                        size = excluded.size,
                        mtime = excluded.mtime,
                        file_hash = excluded.file_hash,
                        updated_at = excluded.updated_at
                    """,
                    [
                        (
                            record.movie_id,
                            record.dest_path,
                            record.source_path,
                            record.kind,
                            1 if record.managed else 0,
                            record.source_dev,
                            record.source_inode,
                            record.size,
                            record.mtime,
                            record.file_hash,
                        )
                        for record in records
                    ],
                )
            self._maybe_run_maintenance()

    def _maybe_run_maintenance(self) -> None:
        now = time.time()
        if now - self._last_maintenance < _MAINTENANCE_INTERVAL:
            return
        self._last_maintenance = now
        try:
            with self._lock:
                with self._connect() as connection:
                    result = connection.execute("PRAGMA integrity_check").fetchone()
                    if result and result[0] != "ok":
                        LOG.error("SQLite integrity check failed: %s", result[0])
                    connection.execute("PRAGMA optimize")
        except sqlite3.DatabaseError as exc:
            LOG.warning("SQLite maintenance failed: %s", exc)
