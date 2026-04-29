from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import requests

LOG = logging.getLogger(__name__)


class RadarrClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = 30,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.5,
        refresh_debounce_seconds: int = 15,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_cooldown: float = 300.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = max(1, int(timeout))
        self.retry_attempts = max(0, int(retry_attempts))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.refresh_debounce_seconds = max(0, int(refresh_debounce_seconds))
        self._last_refresh_by_movie_id: dict[int, float] = {}
        self._cb_threshold = max(1, int(circuit_breaker_threshold))
        self._cb_cooldown = max(0.0, float(circuit_breaker_cooldown))
        self._cb_consecutive_failures = 0
        self._cb_open_since: float | None = None
        self.session = requests.Session()
        self.session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v3{path}"

    def _is_retriable_status_code(self, status_code: int | None) -> bool:
        return status_code in {408, 429, 500, 502, 503, 504}

    def _is_idempotent_method(self, method: str) -> bool:
        return method.upper() in {"GET", "PUT", "DELETE", "HEAD", "OPTIONS"}

    def _retry_delay_seconds(self, attempt: int) -> float:
        return self.retry_backoff_seconds * (2**attempt)

    def _can_retry_request(self, method: str, exc: requests.RequestException) -> bool:
        if self.retry_attempts <= 0 or not self._is_idempotent_method(method):
            return False

        if isinstance(exc, requests.Timeout | requests.ConnectionError):
            return True

        if isinstance(exc, requests.HTTPError):
            response = exc.response
            status_code = response.status_code if response is not None else None
            return self._is_retriable_status_code(status_code)

        return False

    def _log_retry_attempt(self, method: str, path: str, attempt: int, exc: Exception) -> None:
        delay_seconds = self._retry_delay_seconds(attempt)
        LOG.warning(
            "Retrying Radarr request: %s %s attempt=%s/%s delay=%.2fs reason=%s",
            method,
            path,
            attempt + 1,
            self.retry_attempts,
            delay_seconds,
            exc,
        )

    def _check_circuit_breaker(self) -> None:
        if self._cb_open_since is None:
            return
        elapsed = time.time() - self._cb_open_since
        if elapsed < self._cb_cooldown:
            raise requests.ConnectionError(
                f"Radarr circuit breaker is open ({self._cb_consecutive_failures} consecutive "
                f"failures, {self._cb_cooldown - elapsed:.0f}s remaining in cooldown)"
            )
        LOG.info("Radarr circuit breaker closed after %.0fs cooldown", elapsed)
        self._cb_consecutive_failures = 0
        self._cb_open_since = None

    def _record_cb_success(self) -> None:
        if self._cb_consecutive_failures > 0:
            self._cb_consecutive_failures = 0
            self._cb_open_since = None

    def _record_cb_failure(self) -> None:
        self._cb_consecutive_failures += 1
        if self._cb_consecutive_failures >= self._cb_threshold and self._cb_open_since is None:
            self._cb_open_since = time.time()
            LOG.warning(
                "Radarr circuit breaker opened after %s consecutive failures, cooldown=%.0fs",
                self._cb_consecutive_failures,
                self._cb_cooldown,
            )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        self._check_circuit_breaker()
        method_name = method.upper()
        total_attempts = self.retry_attempts + 1

        for attempt in range(total_attempts):
            try:
                started = time.monotonic()
                response = self.session.request(
                    method_name,
                    self._url(path),
                    timeout=self.timeout,
                    **kwargs,
                )
                response.raise_for_status()
                self._record_cb_success()
                elapsed = time.monotonic() - started
                LOG.debug(
                    "Radarr request succeeded: %s %s status=%s elapsed=%.3fs",
                    method_name,
                    path,
                    getattr(response, "status_code", "?"),
                    elapsed,
                )
                if response.content:
                    return response.json()
                return None
            except requests.RequestException as exc:
                LOG.debug("Radarr request failed: %s %s error=%s", method_name, path, exc)
                if attempt >= self.retry_attempts or not self._can_retry_request(method_name, exc):
                    self._record_cb_failure()
                    raise
                self._log_retry_attempt(method_name, path, attempt, exc)
                time.sleep(self._retry_delay_seconds(attempt))

        return None

    def get_movies(self) -> list[dict[str, Any]]:
        return self._request("GET", "/movie")

    def get_movie(self, movie_id: int) -> dict[str, Any] | None:
        movie = self._request("GET", f"/movie/{movie_id}")
        return movie if isinstance(movie, dict) else None

    def get_movies_by_ids(self, movie_ids: Iterable[int]) -> list[dict[str, Any]]:
        movies: list[dict[str, Any]] = []
        unique_ids = sorted(
            {
                int(movie_id)
                for movie_id in movie_ids
                if isinstance(movie_id, int) and not isinstance(movie_id, bool)
            }
        )

        for movie_id in unique_ids:
            try:
                movie = self.get_movie(movie_id)
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 404:
                    LOG.debug("Scoped Radarr movie id not found: %s", movie_id)
                    continue
                raise
            if movie is not None:
                movies.append(movie)

        return movies

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

    def get_root_folders(self) -> list[dict[str, Any]]:
        folders = self._request("GET", "/rootfolder")
        return folders if isinstance(folders, list) else []

    def get_tags(self) -> list[dict[str, Any]]:
        tags = self._request("GET", "/tag")
        return tags if isinstance(tags, list) else []

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

    def update_movie_path(self, movie: dict[str, Any], new_path: str) -> bool:
        previous_path = movie.get("path")
        if previous_path == new_path:
            return False

        payload = dict(movie)
        payload["path"] = new_path
        self._request("PUT", f"/movie/{movie['id']}", json=payload)
        movie["path"] = new_path
        LOG.info(
            "Updated Radarr movie path: %s | %s -> %s",
            movie.get("title"),
            previous_path,
            new_path,
        )
        return True

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

    def refresh_movie(self, movie_id: int, force: bool = False) -> bool:
        now = time.time()
        if not force and self.refresh_debounce_seconds > 0:
            last_refresh = self._last_refresh_by_movie_id.get(movie_id)
            if last_refresh is not None:
                elapsed = now - last_refresh
                if elapsed < self.refresh_debounce_seconds:
                    LOG.debug(
                        "Skipped RefreshMovie due to debounce: "
                        "movie_id=%s elapsed=%.2fs window=%ss",
                        movie_id,
                        elapsed,
                        self.refresh_debounce_seconds,
                    )
                    return False

        self._request("POST", "/command", json={"name": "RefreshMovie", "movieIds": [movie_id]})
        self._last_refresh_by_movie_id[movie_id] = now
        return True

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
