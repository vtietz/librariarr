from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from ..projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from .common import LOG


class ServicePreflightMixin:
    def _log_arr_sync_config_hints(self, exc: Exception) -> None:
        self._log_sync_config_hint(exc)
        self._log_sonarr_sync_config_hint(exc)

    def _log_sync_config_hint(self, exc: Exception) -> None:
        if not self.sync_enabled or self._sync_hint_logged:
            return

        request_exc = self._extract_request_exception(exc)
        if request_exc is None:
            return

        if isinstance(request_exc, requests.HTTPError):
            status_code = (
                request_exc.response.status_code if request_exc.response is not None else None
            )
            if status_code in (401, 403):
                LOG.error(
                    "Radarr API auth failed while sync is enabled (status=%s). "
                    "Review radarr.url/radarr.api_key (or LIBRARIARR_RADARR_URL/"
                    "LIBRARIARR_RADARR_API_KEY), or set radarr.sync_enabled=false "
                    "for filesystem-only mode.",
                    status_code,
                )
                self._sync_hint_logged = True
                return

            if status_code is not None:
                LOG.warning(
                    "Radarr API request failed while sync is enabled (status=%s). "
                    "Review Radarr URL/API key, or disable sync for filesystem-only mode. "
                    "url=%s",
                    status_code,
                    self.config.radarr.url,
                )
                self._sync_hint_logged = True
                return

        if isinstance(request_exc, requests.ConnectionError):
            LOG.warning(
                "Radarr is unreachable while sync is enabled. "
                "Review radarr.url/network/API key, or set radarr.sync_enabled=false "
                "for filesystem-only mode. url=%s error=%s",
                self.config.radarr.url,
                request_exc,
            )
            self._sync_hint_logged = True
            return

        if isinstance(request_exc, requests.Timeout):
            LOG.warning(
                "Radarr request timed out while sync is enabled. "
                "Review radarr.url/network latency/API key, or set "
                "radarr.sync_enabled=false for filesystem-only mode. "
                "url=%s error=%s",
                self.config.radarr.url,
                request_exc,
            )
            self._sync_hint_logged = True
            return

        LOG.warning(
            "Radarr is unreachable while sync is enabled. Review radarr.url/network/API key, "
            "or set radarr.sync_enabled=false for filesystem-only mode. "
            "url=%s error_type=%s",
            self.config.radarr.url,
            type(request_exc).__name__,
        )
        self._sync_hint_logged = True

    def _log_sonarr_sync_config_hint(self, exc: Exception) -> None:
        if not self.sonarr_sync_enabled or self._sonarr_sync_hint_logged:
            return

        request_exc = self._extract_request_exception(exc)
        if request_exc is None:
            return

        if isinstance(request_exc, requests.HTTPError):
            status_code = (
                request_exc.response.status_code if request_exc.response is not None else None
            )
            if status_code in (401, 403):
                LOG.error(
                    "Sonarr API auth failed while sync is enabled (status=%s). "
                    "Review sonarr.url/sonarr.api_key (or LIBRARIARR_SONARR_URL/"
                    "LIBRARIARR_SONARR_API_KEY), or set sonarr.sync_enabled=false "
                    "for filesystem-only mode.",
                    status_code,
                )
                self._sonarr_sync_hint_logged = True
                return

            if status_code is not None:
                LOG.warning(
                    "Sonarr API request failed while sync is enabled (status=%s). "
                    "Review Sonarr URL/API key, or disable sync for filesystem-only mode. "
                    "url=%s",
                    status_code,
                    self.config.sonarr.url,
                )
                self._sonarr_sync_hint_logged = True
                return

        if isinstance(request_exc, requests.ConnectionError):
            LOG.warning(
                "Sonarr is unreachable while sync is enabled. "
                "Review sonarr.url/network/API key, or set sonarr.sync_enabled=false "
                "for filesystem-only mode. url=%s error=%s",
                self.config.sonarr.url,
                request_exc,
            )
            self._sonarr_sync_hint_logged = True
            return

        if isinstance(request_exc, requests.Timeout):
            LOG.warning(
                "Sonarr request timed out while sync is enabled. "
                "Review sonarr.url/network latency/API key, or set "
                "sonarr.sync_enabled=false for filesystem-only mode. "
                "url=%s error=%s",
                self.config.sonarr.url,
                request_exc,
            )
            self._sonarr_sync_hint_logged = True
            return

        LOG.warning(
            "Sonarr is unreachable while sync is enabled. Review sonarr.url/network/API key, "
            "or set sonarr.sync_enabled=false for filesystem-only mode. "
            "url=%s error_type=%s",
            self.config.sonarr.url,
            type(request_exc).__name__,
        )
        self._sonarr_sync_hint_logged = True

    def _extract_request_exception(self, exc: Exception) -> requests.RequestException | None:
        current: BaseException | None = exc
        seen: set[int] = set()

        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, requests.RequestException):
                return current
            current = current.__cause__ or current.__context__
        return None

    def _run_sync_preflight_checks(self) -> None:
        LOG.info("")
        LOG.info("-------------------- Preflight --------------------")
        if not self.radarr_enabled:
            self._run_sonarr_preflight_checks()
            self._update_arr_root_folder_availability(force=True)
            LOG.info("------------------ Preflight Done -----------------")
            return

        if not self.sync_enabled:
            self._run_sonarr_preflight_checks()
            self._update_arr_root_folder_availability(force=True)
            LOG.info("------------------ Preflight Done -----------------")
            return

        parsed_url = urlparse(self.config.radarr.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            LOG.warning(
                "Radarr URL sanity check failed while sync is enabled. "
                "Expected an absolute http(s) URL. current_url=%s",
                self.config.radarr.url,
            )

        if not self.config.radarr.api_key.strip():
            LOG.warning(
                "Radarr sync is enabled but radarr.api_key is empty. "
                "Set radarr.api_key (or LIBRARIARR_RADARR_API_KEY) or disable sync."
            )

        if parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}:
            LOG.warning(
                "Radarr URL uses localhost while sync is enabled (url=%s). "
                "If LibrariArr runs in Docker, localhost points to the LibrariArr container.",
                self.config.radarr.url,
            )

        try:
            status = self.radarr.get_system_status()
            version = str(status.get("version", "unknown"))
            app_name = str(status.get("appName", "Radarr"))
            LOG.info(
                "Radarr preflight check succeeded: app=%s version=%s url=%s",
                app_name,
                version,
                self.config.radarr.url,
            )
            self.radarr_sync.log_quality_mapping_diagnostics(
                auto_add_unmatched=self.auto_add_unmatched,
            )
        except Exception as exc:
            self._log_sync_config_hint(exc)
            request_exc = self._extract_request_exception(exc)
            detail = request_exc if request_exc is not None else exc
            LOG.warning(
                "Radarr preflight check failed; initial reconcile may fail as well. "
                "url=%s error=%s",
                self.config.radarr.url,
                detail,
            )
        self._run_sonarr_preflight_checks()
        self._update_arr_root_folder_availability(force=True)
        LOG.info("------------------ Preflight Done -----------------")

    def _run_sonarr_preflight_checks(self) -> None:
        if not self.sonarr_sync_enabled:
            return

        parsed_url = urlparse(self.config.sonarr.url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            LOG.warning(
                "Sonarr URL sanity check failed while sync is enabled. "
                "Expected an absolute http(s) URL. current_url=%s",
                self.config.sonarr.url,
            )

        if not self.config.sonarr.api_key.strip():
            LOG.warning(
                "Sonarr sync is enabled but sonarr.api_key is empty. "
                "Set sonarr.api_key (or LIBRARIARR_SONARR_API_KEY) or disable sync."
            )

        if parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}:
            LOG.warning(
                "Sonarr URL uses localhost while sync is enabled (url=%s). "
                "If LibrariArr runs in Docker, localhost points to the LibrariArr container.",
                self.config.sonarr.url,
            )

        try:
            status = self.sonarr.get_system_status()
            version = str(status.get("version", "unknown"))
            app_name = str(status.get("appName", "Sonarr"))
            LOG.info(
                "Sonarr preflight check succeeded: app=%s version=%s url=%s",
                app_name,
                version,
                self.config.sonarr.url,
            )
            self.sonarr_sync.log_profile_mapping_diagnostics(
                auto_add_unmatched=self.sonarr_auto_add_unmatched,
            )
        except Exception as exc:
            self._log_sonarr_sync_config_hint(exc)
            request_exc = self._extract_request_exception(exc)
            detail = request_exc if request_exc is not None else exc
            LOG.warning(
                "Sonarr preflight check failed; initial reconcile may fail as well. "
                "url=%s error=%s",
                self.config.sonarr.url,
                detail,
            )

    def _poll_arr_root_reconcile_trigger(self) -> bool:
        radarr_queue_pending = get_radarr_webhook_queue().has_pending()
        sonarr_queue_pending = get_sonarr_webhook_queue().has_pending()
        root_poll_triggered = self._update_arr_root_folder_availability(force=False)
        return radarr_queue_pending or sonarr_queue_pending or root_poll_triggered

    def _normalize_arr_root_path(self, value: str) -> str:
        return str(value).strip().rstrip("/\\")

    def _configured_sonarr_managed_root_paths(self) -> set[str]:
        return {
            self._normalize_arr_root_path(str(managed_root))
            for managed_root, _ in self.root_mappings
        }

    def _configured_radarr_root_paths(self) -> set[str]:
        return {
            self._normalize_arr_root_path(str(managed_root))
            for managed_root, _ in self.movie_root_mappings
        }

    def _extract_arr_root_paths(self, payload: list[dict]) -> set[str]:
        out: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                continue
            raw_path = item.get("path")
            if raw_path is None:
                continue
            normalized = self._normalize_arr_root_path(str(raw_path))
            if not normalized:
                continue
            out.add(normalized)
        return out

    def _update_missing_roots_state(
        self,
        arr_name: str,
        missing: set[str],
        previous_missing: set[str],
    ) -> tuple[set[str], bool]:
        if missing == previous_missing:
            return missing, False

        newly_available = sorted(previous_missing - missing)
        newly_missing = sorted(missing - previous_missing)

        if newly_available:
            formatted = "\n  - ".join(newly_available)
            LOG.info(
                "%s root folders became available:\n  - %s",
                arr_name,
                formatted,
            )
        if newly_missing:
            formatted = "\n  - ".join(newly_missing)
            LOG.info(
                "%s root folders configured in LibrariArr but missing in %s:\n  - %s",
                arr_name,
                arr_name,
                formatted,
            )

        became_available = bool(newly_available)
        return missing, became_available

    def _refresh_radarr_missing_roots(self) -> bool:
        if not self.sync_enabled:
            self._radarr_missing_managed_roots = set()
            return False

        try:
            configured = self._configured_radarr_root_paths()
            available = self._extract_arr_root_paths(self.radarr.get_root_folders())
        except Exception as exc:
            self._log_sync_config_hint(exc)
            return False

        missing = configured - available
        self._radarr_missing_managed_roots, became_available = self._update_missing_roots_state(
            "Radarr",
            missing,
            self._radarr_missing_managed_roots,
        )
        return became_available

    def _refresh_sonarr_missing_roots(self) -> bool:
        if not self.sonarr_sync_enabled:
            self._sonarr_missing_managed_roots = set()
            return False

        try:
            configured = self._configured_sonarr_managed_root_paths()
            available = self._extract_arr_root_paths(self.sonarr.get_root_folders())
        except Exception as exc:
            self._log_sonarr_sync_config_hint(exc)
            return False

        missing = configured - available
        self._sonarr_missing_managed_roots, became_available = self._update_missing_roots_state(
            "Sonarr",
            missing,
            self._sonarr_missing_managed_roots,
        )
        return became_available

    def _update_arr_root_folder_availability(self, force: bool) -> bool:
        if self._arr_root_poll_interval is None and not force:
            return False

        now = time.time()
        if not force and now < self._next_arr_root_poll_at:
            return False

        interval = self._arr_root_poll_interval if self._arr_root_poll_interval is not None else 0
        self._next_arr_root_poll_at = now + max(1, interval)

        radarr_became_available = self._refresh_radarr_missing_roots()
        sonarr_became_available = self._refresh_sonarr_missing_roots()
        return radarr_became_available or sonarr_became_available
