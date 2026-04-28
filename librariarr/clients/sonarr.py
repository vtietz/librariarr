from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from typing import Any

import requests

LOG = logging.getLogger(__name__)


class SonarrClient:
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
        self._last_refresh_by_series_id: dict[int, float] = {}
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
            "Retrying Sonarr request: %s %s attempt=%s/%s delay=%.2fs reason=%s",
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
                f"Sonarr circuit breaker is open ({self._cb_consecutive_failures} consecutive "
                f"failures, {self._cb_cooldown - elapsed:.0f}s remaining in cooldown)"
            )
        LOG.info("Sonarr circuit breaker closed after %.0fs cooldown", elapsed)
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
                "Sonarr circuit breaker opened after %s consecutive failures, cooldown=%.0fs",
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
                    "Sonarr request succeeded: %s %s status=%s elapsed=%.3fs",
                    method_name,
                    path,
                    getattr(response, "status_code", "?"),
                    elapsed,
                )
                if response.content:
                    return response.json()
                return None
            except requests.RequestException as exc:
                LOG.debug("Sonarr request failed: %s %s error=%s", method_name, path, exc)
                if attempt >= self.retry_attempts or not self._can_retry_request(method_name, exc):
                    self._record_cb_failure()
                    raise
                self._log_retry_attempt(method_name, path, attempt, exc)
                time.sleep(self._retry_delay_seconds(attempt))

        return None

    def get_series(self) -> list[dict[str, Any]]:
        series = self._request("GET", "/series")
        return series if isinstance(series, list) else []

    def get_series_item(self, series_id: int) -> dict[str, Any] | None:
        item = self._request("GET", f"/series/{series_id}")
        return item if isinstance(item, dict) else None

    def get_series_by_ids(self, series_ids: Iterable[int]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        unique_ids = sorted(
            {int(sid) for sid in series_ids if isinstance(sid, int) and not isinstance(sid, bool)}
        )

        for sid in unique_ids:
            try:
                item = self.get_series_item(sid)
            except requests.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 404:
                    LOG.debug("Scoped Sonarr series id not found: %s", sid)
                    continue
                raise
            if item is not None:
                result.append(item)

        return result

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

    def get_tags(self) -> list[dict[str, Any]]:
        tags = self._request("GET", "/tag")
        return tags if isinstance(tags, list) else []

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
        previous_path = series.get("path")
        if previous_path == new_path:
            return False

        payload = dict(series)
        payload["path"] = new_path
        self._request("PUT", f"/series/{series['id']}", json=payload)
        LOG.info(
            "Updated Sonarr series path in Arr DB (no file move): %s | %s -> %s",
            series.get("title"),
            previous_path,
            new_path,
        )
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
