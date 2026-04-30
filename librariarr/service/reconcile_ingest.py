"""Ingest mixin: moves files/folders from library roots into managed roots."""

from __future__ import annotations

from pathlib import Path

from .common import LOG
from .reconcile_helpers import (
    folder_matches_affected_paths,
    ingest_files_from_library_folder,
)


class ServiceIngestMixin:
    """Methods for ingesting movie files from library roots into managed roots."""

    def _ingest_movies_from_library_roots(
        self,
        affected_paths: set[Path] | None,
        movies_inventory: list[dict] | None = None,
    ) -> set[int]:
        if not (self.radarr_enabled and self.sync_enabled and self.config.ingest.enabled):
            return set()

        if movies_inventory is not None:
            movies = movies_inventory
        else:
            try:
                movies = self.radarr.get_movies()
            except Exception as exc:
                self._log_sync_config_hint(exc)
                LOG.warning("Skipping ingest: Radarr inventory fetch failed: %s", exc)
                return set()

        moved_movie_ids: set[int] = set()
        tracker = getattr(self, "runtime_status_tracker", None)
        total_movies = len(movies)
        if tracker is not None and total_movies > 0:
            tracker.update_reconcile_phase("ingest_movies")
            tracker.update_active_reconcile_metrics(
                {
                    "movie_items_processed": 0,
                    "movie_items_total": total_movies,
                }
            )

        for index, movie in enumerate(movies, start=1):
            moved_movie_id = self._ingest_movie_if_needed(
                movie,
                affected_paths=affected_paths,
            )
            if moved_movie_id is not None:
                moved_movie_ids.add(moved_movie_id)

            if tracker is not None and (index == total_movies or index % 25 == 0):
                tracker.update_reconcile_phase("ingest_movies")
                tracker.update_active_reconcile_metrics(
                    {
                        "movie_items_processed": index,
                        "movie_items_total": total_movies,
                    }
                )

        return moved_movie_ids

    def _ingest_movie_if_needed(
        self,
        movie: dict,
        *,
        affected_paths: set[Path] | None,
    ) -> int | None:
        movie_id = movie.get("id")
        movie_path_raw = str(movie.get("path") or "").strip()
        if not isinstance(movie_id, int) or not movie_path_raw:
            return None

        source_folder = Path(movie_path_raw)
        # Skip whole-folder ingest when source is a projection output.
        # If the provenance DB has projected dest files under the current
        # source folder, the folder was created by projection, not downloaded.
        if self._source_is_projected_folder(movie_id, source_folder):
            return self._ingest_files_for_existing_movie(
                movie_id,
                source_folder,
                affected_paths=affected_paths,
            )
        destination_info = self._resolve_ingest_target(
            source_folder,
            affected_paths=affected_paths,
        )
        if destination_info is not None:
            managed_root, resolved_destination = destination_info
            if not _move_folder(source_folder, resolved_destination):
                return None
            LOG.info(
                "Ingest moved movie folder from library root to managed root: movie_id=%s "
                "source=%s destination=%s",
                movie_id,
                source_folder,
                resolved_destination,
            )
            return movie_id

        return self._ingest_files_for_existing_movie(
            movie_id,
            source_folder,
            affected_paths=affected_paths,
        )

    def _ingest_files_for_existing_movie(
        self,
        movie_id: int,
        source_folder: Path,
        *,
        affected_paths: set[Path] | None,
    ) -> int | None:
        mapping_info = self._resolve_ingest_mapping_for_folder(source_folder)
        if mapping_info is None:
            return None
        managed_root, _library_root, relative_folder = mapping_info
        managed_folder = managed_root / relative_folder
        if not managed_folder.exists() or not managed_folder.is_dir():
            return None
        if not source_folder.exists() or not source_folder.is_dir():
            return None
        if not folder_matches_affected_paths(source_folder, affected_paths):
            return None
        proj = self.config.radarr.projection
        result = ingest_files_from_library_folder(
            library_folder=source_folder,
            managed_folder=managed_folder,
            managed_video_extensions=set(proj.managed_video_extensions),
            extras_allowlist=proj.managed_extras_allowlist,
        )
        if result.ingested_count > 0:
            LOG.info(
                "File-level fs operations for movie_id=%s: moved=%s failed=%s",
                movie_id,
                result.ingested_count,
                result.failed_count,
            )
            return movie_id
        return None

    def _resolve_ingest_target(
        self,
        source_folder: Path,
        *,
        affected_paths: set[Path] | None,
    ) -> tuple[Path, Path] | None:
        mapping_and_relative = self._resolve_ingest_mapping_for_folder(source_folder)
        if mapping_and_relative is None:
            return None
        managed_root, _library_root, relative_folder = mapping_and_relative

        if not source_folder.exists() or not source_folder.is_dir():
            return None
        if not folder_matches_affected_paths(source_folder, affected_paths):
            return None

        destination_folder = managed_root / relative_folder
        if destination_folder.resolve(strict=False) == source_folder.resolve(strict=False):
            return None

        if destination_folder.exists():
            return None

        return managed_root, destination_folder

    def _source_is_projected_folder(self, movie_id: int, source_folder: Path) -> bool:
        """Return True when *source_folder* was created by the projection executor."""
        if self.movie_projection is None:
            return False
        state_store = getattr(self.movie_projection, "state_store", None)
        if state_store is None:
            return False
        source_folder_resolved = source_folder.resolve(strict=False)
        try:
            entries = state_store.get_managed_entries_for_movie(movie_id)
            if not isinstance(entries, list | set | tuple):
                raise TypeError
        except (AttributeError, TypeError):
            managed_paths = state_store.get_managed_paths_for_movie(movie_id)
            entries = [(path, "") for path in managed_paths]
        except Exception:
            return False

        for dest_path_raw, source_path_raw in entries:
            try:
                dest_path = Path(dest_path_raw).resolve(strict=False)
            except Exception:
                continue
            if not dest_path.is_relative_to(source_folder_resolved):
                continue
            if source_path_raw and not Path(source_path_raw).exists():
                # Stale provenance can exist after test/temp cleanup; do not
                # treat those records as proof that the source is projected.
                continue
            return True
        return False

    def _resolve_ingest_mapping_for_folder(
        self,
        folder: Path,
    ) -> tuple[Path, Path, Path] | None:
        sorted_mappings = sorted(
            self.movie_root_mappings,
            key=lambda item: len(item[1].parts),
            reverse=True,
        )
        for managed_root, library_root in sorted_mappings:
            try:
                relative_folder = folder.relative_to(library_root)
            except ValueError:
                continue
            return managed_root, library_root, relative_folder
        return None


def _move_folder(source_folder: Path, resolved_destination: Path) -> bool:
    resolved_destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        source_folder.rename(resolved_destination)
    except OSError as exc:
        LOG.warning(
            "Ingest move failed: source=%s destination=%s error=%s",
            source_folder,
            resolved_destination,
            exc,
        )
        return False
    LOG.info(
        "FS MOVE directory: source=%s destination=%s",
        source_folder,
        resolved_destination,
    )
    return True
