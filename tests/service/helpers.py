from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    IngestConfig,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RadarrMappingConfig,
    RootMapping,
    RuntimeConfig,
)


class FakeRadarr:
    def __init__(
        self,
        movies: list[dict] | None = None,
        system_status: dict | None = None,
        system_status_error: Exception | None = None,
        quality_profiles: list[dict] | None = None,
        quality_definitions: list[dict] | None = None,
        custom_formats: list[dict] | None = None,
        parse_results: dict[str, dict] | None = None,
        lookup_results: list[dict] | None = None,
        add_movie_result: dict | None = None,
        root_folders: list[dict] | None = None,
    ) -> None:
        self.movies = movies or []
        self.system_status = system_status or {"appName": "Radarr", "version": "0.0.0-test"}
        self.system_status_error = system_status_error
        self.quality_profiles = quality_profiles or []
        self.quality_definitions = quality_definitions or []
        self.custom_formats = custom_formats or []
        self.parse_results = parse_results or {}
        self.lookup_results = lookup_results or []
        self.add_movie_result = add_movie_result or {}
        self.root_folders = root_folders
        self.updated_paths: list[tuple[int, str]] = []
        self.updated_qualities: list[tuple[int, int]] = []
        self.refreshed: list[int] = []
        self.unmonitored: list[int] = []
        self.deleted: list[int] = []
        self.lookup_terms: list[str] = []
        self.parse_titles: list[str] = []
        self.added_movies: list[dict] = []
        self.get_movies_calls = 0
        self.get_system_status_calls = 0
        self.get_quality_profiles_calls = 0
        self.get_quality_definitions_calls = 0
        self.get_custom_formats_calls = 0

    def get_movies(self) -> list[dict]:
        self.get_movies_calls += 1
        return self.movies

    def get_system_status(self) -> dict:
        self.get_system_status_calls += 1
        if self.system_status_error is not None:
            raise self.system_status_error
        return self.system_status

    def get_quality_profiles(self) -> list[dict]:
        self.get_quality_profiles_calls += 1
        return self.quality_profiles

    def get_quality_definitions(self) -> list[dict]:
        self.get_quality_definitions_calls += 1
        return self.quality_definitions

    def get_custom_formats(self) -> list[dict]:
        self.get_custom_formats_calls += 1
        return self.custom_formats

    def get_root_folders(self) -> list[dict]:
        if self.root_folders is None:
            raise NotImplementedError
        return self.root_folders

    def lookup_movies(self, term: str) -> list[dict]:
        self.lookup_terms.append(term)
        return self.lookup_results

    def parse_title(self, title: str) -> dict:
        self.parse_titles.append(title)
        return self.parse_results.get(title, {})

    def add_movie_from_lookup(
        self,
        lookup_movie: dict,
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        monitored: bool,
        search_for_movie: bool,
    ) -> dict:
        self.added_movies.append(
            {
                "lookup_movie": lookup_movie,
                "path": path,
                "root_folder_path": root_folder_path,
                "quality_profile_id": quality_profile_id,
                "monitored": monitored,
                "search_for_movie": search_for_movie,
            }
        )
        return self.add_movie_result

    def update_movie_path(self, movie: dict, new_path: str) -> bool:
        if movie.get("path") == new_path:
            return False
        self.updated_paths.append((int(movie["id"]), new_path))
        movie["path"] = new_path
        return True

    def try_update_moviefile_quality(self, movie: dict, quality_id: int) -> bool:
        self.updated_qualities.append((int(movie["id"]), quality_id))
        return True

    def refresh_movie(self, movie_id: int, force: bool = False) -> None:
        del force
        self.refreshed.append(movie_id)

    def unmonitor_movie(self, movie: dict) -> None:
        self.unmonitored.append(int(movie["id"]))

    def delete_movie(
        self,
        movie_id: int,
        delete_files: bool = False,
        add_import_exclusion: bool = False,
    ) -> None:
        del delete_files
        del add_import_exclusion
        self.deleted.append(movie_id)


def make_config(
    nested_root: Path,
    shadow_root: Path,
    sync_enabled: bool = True,
    radarr_enabled: bool = True,
    delete_from_radarr_on_missing: bool = False,
    auto_add_unmatched: bool = False,
    auto_add_quality_profile_id: int | None = None,
) -> AppConfig:
    return AppConfig(
        paths=PathsConfig(
            root_mappings=[RootMapping(nested_root=str(nested_root), shadow_root=str(shadow_root))]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test",
            enabled=radarr_enabled,
            sync_enabled=sync_enabled,
            auto_add_unmatched=auto_add_unmatched,
            auto_add_quality_profile_id=auto_add_quality_profile_id,
            mapping=RadarrMappingConfig(
                quality_map=[QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")]
            ),
        ),
        cleanup=CleanupConfig(
            remove_orphaned_links=True,
            unmonitor_on_delete=True,
            delete_from_radarr_on_missing=delete_from_radarr_on_missing,
            missing_grace_seconds=0,
        ),
        runtime=RuntimeConfig(
            debounce_seconds=1,
            maintenance_interval_minutes=60,
            arr_root_poll_interval_minutes=0,
        ),
        ingest=IngestConfig(),
    )
