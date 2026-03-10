from __future__ import annotations

import logging
from typing import Any

import requests

LOG = logging.getLogger(__name__)


class RadarrClient:
    def __init__(self, base_url: str, api_key: str, timeout: int = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
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

    def get_movies(self) -> list[dict[str, Any]]:
        return self._request("GET", "/movie")

    def get_system_status(self) -> dict[str, Any]:
        status = self._request("GET", "/system/status")
        return status if isinstance(status, dict) else {}

    def get_quality_profiles(self) -> list[dict[str, Any]]:
        profiles = self._request("GET", "/qualityprofile")
        return profiles if isinstance(profiles, list) else []

    def get_quality_definitions(self) -> list[dict[str, Any]]:
        definitions = self._request("GET", "/qualitydefinition")
        return definitions if isinstance(definitions, list) else []

    def get_custom_formats(self) -> list[dict[str, Any]]:
        formats = self._request("GET", "/customformat")
        return formats if isinstance(formats, list) else []

    def lookup_movies(self, term: str) -> list[dict[str, Any]]:
        results = self._request("GET", "/movie/lookup", params={"term": term})
        return results if isinstance(results, list) else []

    def parse_title(self, title: str) -> dict[str, Any]:
        parsed = self._request("GET", "/parse", params={"title": title})
        return parsed if isinstance(parsed, dict) else {}

    def add_movie_from_lookup(
        self,
        lookup_movie: dict[str, Any],
        path: str,
        root_folder_path: str,
        quality_profile_id: int,
        monitored: bool,
        search_for_movie: bool,
    ) -> dict[str, Any]:
        payload = dict(lookup_movie)
        payload["id"] = 0
        payload["path"] = path
        payload["rootFolderPath"] = root_folder_path
        payload["qualityProfileId"] = quality_profile_id
        payload["monitored"] = monitored
        payload["addOptions"] = {
            "searchForMovie": search_for_movie,
        }
        added = self._request("POST", "/movie", json=payload)
        return added if isinstance(added, dict) else {}

    def update_movie_path(self, movie: dict[str, Any], new_path: str) -> None:
        if movie.get("path") == new_path:
            return

        payload = dict(movie)
        payload["path"] = new_path
        self._request("PUT", f"/movie/{movie['id']}", json=payload)
        LOG.info("Updated movie path: %s -> %s", movie.get("title"), new_path)

    def unmonitor_movie(self, movie: dict[str, Any]) -> None:
        if movie.get("monitored") is False:
            return
        payload = dict(movie)
        payload["monitored"] = False
        self._request("PUT", f"/movie/{movie['id']}", json=payload)
        LOG.info("Unmonitored movie: %s", movie.get("title"))

    def delete_movie(
        self,
        movie_id: int,
        delete_files: bool = False,
        add_import_exclusion: bool = False,
    ) -> None:
        params = {
            "deleteFiles": str(delete_files).lower(),
            "addImportExclusion": str(add_import_exclusion).lower(),
        }
        self._request("DELETE", f"/movie/{movie_id}", params=params)
        LOG.info("Deleted movie from Radarr DB: id=%s", movie_id)

    def refresh_movie(self, movie_id: int) -> None:
        self._request("POST", "/command", json={"name": "RefreshMovie", "movieIds": [movie_id]})

    def _moviefile_quality_id(self, movie_file: dict[str, Any]) -> int | None:
        quality = movie_file.get("quality")
        if not isinstance(quality, dict):
            return None

        quality_item = quality.get("quality")
        if not isinstance(quality_item, dict):
            return None

        current_id = quality_item.get("id")
        return current_id if isinstance(current_id, int) else None

    def try_update_moviefile_quality(self, movie: dict[str, Any], quality_id: int) -> bool:
        movie_file = movie.get("movieFile")
        if not movie_file:
            return False
        movie_file_id = movie_file.get("id")
        if not movie_file_id:
            return False

        current_quality_id = self._moviefile_quality_id(movie_file)
        if current_quality_id == quality_id:
            return False

        payload = {
            "movieFileIds": [movie_file_id],
            "quality": {
                "quality": {"id": quality_id, "name": "LibrariArrMapped"},
                "revision": {"version": 1, "real": 0, "isRepack": False},
            },
        }

        try:
            self._request("PUT", "/moviefile/editor", json=payload)
            LOG.info("Set quality id=%s for movie=%s", quality_id, movie.get("title"))
            return True
        except requests.HTTPError as exc:
            # Radarr endpoints vary by version. Keep path sync even if quality update fails.
            LOG.warning("Quality update failed for movie=%s: %s", movie.get("title"), exc)
            return False
