from __future__ import annotations

import time
from datetime import UTC, datetime
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
        history_poll_triggered = self._poll_arr_history_safety_trigger()
        return (
            radarr_queue_pending
            or sonarr_queue_pending
            or root_poll_triggered
            or history_poll_triggered
        )

    def _poll_arr_history_safety_trigger(self) -> bool:
        if self._arr_event_safety_poll_interval is None:
            return False

        now = time.time()
        if now < self._next_arr_event_safety_poll_at:
            return False

        self._next_arr_event_safety_poll_at = now + max(1, self._arr_event_safety_poll_interval)
        radarr_triggered = self._poll_radarr_history_for_safety_events()
        sonarr_triggered = self._poll_sonarr_history_for_safety_events()
        return radarr_triggered or sonarr_triggered

    def _poll_radarr_history_for_safety_events(self) -> bool:
        if not self.sync_enabled:
            return False

        return self._poll_arr_history_events(
            arr_name="Radarr",
            cursor_attr="_radarr_event_safety_cursor_id",
            fetch_records=lambda: self.radarr.get_history(
                page=1,
                page_size=self._arr_event_safety_history_page_size,
                sort_direction="descending",
            ),
            id_extractor=self._extract_radarr_history_movie_id,
            enqueue=lambda item_id, event_type, normalized_path: get_radarr_webhook_queue().enqueue(
                movie_id=item_id,
                event_type=f"safety:{event_type}",
                normalized_path=normalized_path,
            ),
        )

    def _poll_sonarr_history_for_safety_events(self) -> bool:
        if not self.sonarr_sync_enabled:
            return False

        return self._poll_arr_history_events(
            arr_name="Sonarr",
            cursor_attr="_sonarr_event_safety_cursor_id",
            fetch_records=lambda: self.sonarr.get_history(
                page=1,
                page_size=self._arr_event_safety_history_page_size,
                sort_direction="descending",
            ),
            id_extractor=self._extract_sonarr_history_series_id,
            enqueue=lambda item_id, event_type, normalized_path: get_sonarr_webhook_queue().enqueue(
                series_id=item_id,
                event_type=f"safety:{event_type}",
                normalized_path=normalized_path,
            ),
        )

    def _poll_arr_history_events(
        self,
        *,
        arr_name: str,
        cursor_attr: str,
        fetch_records,
        id_extractor,
        enqueue,
    ) -> bool:
        try:
            records = fetch_records()
        except Exception as exc:
            if arr_name == "Radarr":
                self._log_sync_config_hint(exc)
            else:
                self._log_sonarr_sync_config_hint(exc)
            LOG.debug("%s safety history poll failed: %s", arr_name, exc)
            return False

        if not records:
            return False

        cursor_id = getattr(self, cursor_attr)
        lookback_cutoff = self._history_bootstrap_cutoff_epoch(cursor_id)
        latest_id = cursor_id
        queued_any = False
        queued_ids: set[int] = set()

        for record in sorted(records, key=self._history_record_id):
            event_id, queued_item_id = self._process_arr_history_record(
                record=record,
                cursor_id=cursor_id,
                lookback_cutoff=lookback_cutoff,
                id_extractor=id_extractor,
                enqueue=enqueue,
            )
            if event_id is None:
                continue
            latest_id = event_id if latest_id is None else max(latest_id, event_id)
            if queued_item_id is None:
                continue
            queued_any = True
            queued_ids.add(queued_item_id)

        if latest_id is not None:
            setattr(self, cursor_attr, latest_id)

        if queued_any:
            LOG.info(
                "%s safety history poll queued scoped reconcile ids=%s",
                arr_name,
                sorted(queued_ids),
            )
        return queued_any

    def _process_arr_history_record(
        self,
        *,
        record: dict,
        cursor_id: int | None,
        lookback_cutoff: float | None,
        id_extractor,
        enqueue,
    ) -> tuple[int | None, int | None]:
        event_id = self._history_record_id(record)
        if event_id is None:
            return None, None
        if not self._should_process_history_record(record, event_id, cursor_id, lookback_cutoff):
            return event_id, None

        item_id = id_extractor(record)
        if item_id is None:
            return event_id, None

        event_type = str(record.get("eventType") or "history")
        normalized_path = self._extract_history_normalized_path(record)
        outcome = enqueue(item_id, event_type, normalized_path)
        if outcome.get("queued"):
            return event_id, item_id
        return event_id, None

    def _should_process_history_record(
        self,
        record: dict,
        event_id: int,
        cursor_id: int | None,
        lookback_cutoff: float | None,
    ) -> bool:
        if cursor_id is not None:
            return event_id > cursor_id
        if lookback_cutoff is None:
            return False
        event_time = self._history_record_epoch(record)
        if event_time is None:
            return True
        return event_time >= lookback_cutoff

    def _history_bootstrap_cutoff_epoch(self, cursor_id: int | None) -> float | None:
        if cursor_id is not None:
            return None
        if self._arr_event_safety_bootstrap_lookback_seconds <= 0:
            return None
        return time.time() - float(self._arr_event_safety_bootstrap_lookback_seconds)

    def _history_record_id(self, record: dict) -> int | None:
        raw = record.get("id")
        if isinstance(raw, int) and not isinstance(raw, bool):
            return raw
        return None

    def _history_record_epoch(self, record: dict) -> float | None:
        raw = record.get("date")
        if not isinstance(raw, str) or not raw.strip():
            return None
        candidate = raw.strip()
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.timestamp()

    def _extract_radarr_history_movie_id(self, record: dict) -> int | None:
        movie_id = record.get("movieId")
        if isinstance(movie_id, int) and not isinstance(movie_id, bool):
            return movie_id
        movie = record.get("movie")
        if isinstance(movie, dict):
            nested_id = movie.get("id")
            if isinstance(nested_id, int) and not isinstance(nested_id, bool):
                return nested_id
        return None

    def _extract_sonarr_history_series_id(self, record: dict) -> int | None:
        series_id = record.get("seriesId")
        if isinstance(series_id, int) and not isinstance(series_id, bool):
            return series_id
        series = record.get("series")
        if isinstance(series, dict):
            nested_id = series.get("id")
            if isinstance(nested_id, int) and not isinstance(nested_id, bool):
                return nested_id
        return None

    def _extract_history_normalized_path(self, record: dict) -> str:
        for key in ("sourcePath", "path", "relativePath"):
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                return str(value).strip()
        return ""

    def _normalize_arr_root_path(self, value: str) -> str:
        return str(value).strip().rstrip("/\\")

    def _configured_sonarr_root_paths(self) -> set[str]:
        return {
            self._normalize_arr_root_path(str(shadow_root))
            for _, shadow_root in self.series_root_mappings
        }

    def _configured_radarr_root_paths(self) -> set[str]:
        return {
            self._normalize_arr_root_path(str(library_root))
            for _, library_root in self.movie_root_mappings
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
            configured = self._configured_sonarr_root_paths()
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
