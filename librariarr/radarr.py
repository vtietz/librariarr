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

    def refresh_movie(self, movie_id: int) -> None:
        self._request("POST", "/command", json={"name": "RefreshMovie", "movieIds": [movie_id]})

    def try_update_moviefile_quality(self, movie: dict[str, Any], quality_id: int) -> None:
        movie_file = movie.get("movieFile")
        if not movie_file:
            return
        movie_file_id = movie_file.get("id")
        if not movie_file_id:
            return

        payload = {
            "movieFileIds": [movie_file_id],
            "quality": {"quality": {"id": quality_id, "name": "LibrariArrMapped"}, "revision": {"version": 1, "real": 0, "isRepack": False}},
        }

        try:
            self._request("PUT", "/moviefile/editor", json=payload)
            LOG.info("Set quality id=%s for movie=%s", quality_id, movie.get("title"))
        except requests.HTTPError as exc:
            # Radarr endpoints/permissions can differ by version. Keep syncing path even if quality update fails.
            LOG.warning("Quality update failed for movie=%s: %s", movie.get("title"), exc)
