from __future__ import annotations

import logging
import time
from typing import Any

import requests

LOG = logging.getLogger(__name__)


class SonarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 20,
        refresh_debounce_seconds: int = 15,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.refresh_debounce_seconds = max(0, int(refresh_debounce_seconds))
        self._last_refresh_by_series_id: dict[int, float] = {}
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v3{path}"

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(method, self._url(path), timeout=self.timeout, **kwargs)
        response.raise_for_status()
        if response.content:
            return response.json()
        return None

    def get_series(self) -> list[dict[str, Any]]:
        series = self._request("GET", "/series")
        return series if isinstance(series, list) else []

    def get_system_status(self) -> dict[str, Any]:
        status = self._request("GET", "/system/status")
        return status if isinstance(status, dict) else {}

    def get_quality_profiles(self) -> list[dict[str, Any]]:
        profiles = self._request("GET", "/qualityprofile")
        return profiles if isinstance(profiles, list) else []

    def get_language_profiles(self) -> list[dict[str, Any]]:
        profiles = self._request("GET", "/languageprofile")
        return profiles if isinstance(profiles, list) else []

    def get_root_folders(self) -> list[dict[str, Any]]:
        folders = self._request("GET", "/rootfolder")
        return folders if isinstance(folders, list) else []

    def lookup_series(self, term: str) -> list[dict[str, Any]]:
        results = self._request("GET", "/series/lookup", params={"term": term})
        return results if isinstance(results, list) else []

    def add_series_from_lookup(
        self,
        lookup_series: dict[str, Any],
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        language_profile_id: int | None,
        monitored: bool,
        season_folder: bool,
        search_for_missing_episodes: bool,
    ) -> dict[str, Any]:
        payload = dict(lookup_series)
        payload["id"] = 0
        payload["path"] = path
        payload["rootFolderPath"] = root_folder_path
        payload["qualityProfileId"] = quality_profile_id
        payload["monitored"] = monitored
        payload["seasonFolder"] = season_folder
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id
        payload["addOptions"] = {
            "searchForMissingEpisodes": search_for_missing_episodes,
            "searchForCutoffUnmetEpisodes": False,
        }
        added = self._request("POST", "/series", json=payload)
        return added if isinstance(added, dict) else {}

    def update_series_path(self, series: dict[str, Any], new_path: str) -> bool:
        if series.get("path") == new_path:
            return False

        payload = dict(series)
        payload["path"] = new_path
        self._request("PUT", f"/series/{series['id']}", json=payload)
        LOG.info("Updated series path: %s -> %s", series.get("title"), new_path)
        return True

    def unmonitor_series(self, series: dict[str, Any]) -> None:
        if series.get("monitored") is False:
            return
        payload = dict(series)
        payload["monitored"] = False
        self._request("PUT", f"/series/{series['id']}", json=payload)
        LOG.info("Unmonitored series: %s", series.get("title"))

    def delete_series(
        self,
        series_id: int,
        delete_files: bool = False,
        add_import_list_exclusion: bool = False,
    ) -> None:
        params = {
            "deleteFiles": str(delete_files).lower(),
            "addImportListExclusion": str(add_import_list_exclusion).lower(),
        }
        self._request("DELETE", f"/series/{series_id}", params=params)
        LOG.info("Deleted series from Sonarr DB: id=%s", series_id)

    def refresh_series(self, series_id: int, force: bool = False) -> bool:
        now = time.time()
        if not force and self.refresh_debounce_seconds > 0:
            last_refresh = self._last_refresh_by_series_id.get(series_id)
            if last_refresh is not None:
                elapsed = now - last_refresh
                if elapsed < self.refresh_debounce_seconds:
                    LOG.debug(
                        "Skipped RefreshSeries due to debounce: "
                        "series_id=%s elapsed=%.2fs window=%ss",
                        series_id,
                        elapsed,
                        self.refresh_debounce_seconds,
                    )
                    return False

        self._request("POST", "/command", json={"name": "RefreshSeries", "seriesId": series_id})
        self._last_refresh_by_series_id[series_id] = now
        return True

    # Compatibility aliases so shared cleanup logic can be reused for both clients.
    def unmonitor_movie(self, movie: dict[str, Any]) -> None:
        self.unmonitor_series(movie)

    def delete_movie(
        self,
        movie_id: int,
        delete_files: bool = False,
        add_import_exclusion: bool = False,
    ) -> None:
        self.delete_series(
            series_id=movie_id,
            delete_files=delete_files,
            add_import_list_exclusion=add_import_exclusion,
        )

    def refresh_movie(self, movie_id: int, force: bool = False) -> bool:
        return self.refresh_series(series_id=movie_id, force=force)
