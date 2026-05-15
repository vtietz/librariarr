from pathlib import Path

import requests

from librariarr.config import CustomFormatRule, QualityRule
from librariarr.projection import get_radarr_webhook_queue, get_sonarr_webhook_queue
from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config


class _FakeSonarr:
    def __init__(self, history_records: list[dict] | None = None) -> None:
        self.history_records = history_records or []

    def get_root_folders(self) -> list[dict]:
        return []

    def get_history(self, **kwargs) -> list[dict]:
        del kwargs
        return list(self.history_records)


class _FakeRadarrWithHistory(FakeRadarr):
    def __init__(self, history_records: list[dict]) -> None:
        super().__init__(root_folders=[])
        self.history_records = list(history_records)

    def get_history(self, **kwargs) -> list[dict]:
        del kwargs
        return list(self.history_records)


def test_sync_hint_logs_actionable_message_for_unauthorized_radarr(
    tmp_path: Path,
    caplog,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    response = requests.Response()
    response.status_code = 401
    response.url = "http://radarr:7878/api/v3/movie"
    err = requests.HTTPError("401 Client Error: Unauthorized", response=response)

    caplog.set_level("ERROR", logger="librariarr.service")
    service._log_sync_config_hint(err)

    assert "Radarr API auth failed while sync is enabled" in caplog.text
    assert "set radarr.sync_enabled=false for filesystem-only mode" in caplog.text

    caplog.clear()
    service._log_sync_config_hint(err)
    assert caplog.text == ""


def test_sync_hint_logs_url_for_connection_errors(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)

    err = requests.ConnectionError("connection refused")

    caplog.set_level("WARNING", logger="librariarr.service")
    service._log_sync_config_hint(err)

    assert "Radarr is unreachable while sync is enabled" in caplog.text
    assert "url=http://radarr:7878" in caplog.text


def test_sync_preflight_warns_for_empty_api_key(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.api_key = ""
    service = LibrariArrService(config)
    service.radarr = FakeRadarr()

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "radarr.api_key is empty" in caplog.text


def test_sync_preflight_logs_failure_details_when_status_probe_fails(
    tmp_path: Path,
    caplog,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(system_status_error=requests.ConnectionError("refused"))

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr preflight check failed" in caplog.text
    assert "error=refused" in caplog.text


def test_sync_preflight_logs_quality_catalog_and_validation(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.quality_map = [
        QualityRule(match=["1080p"], target_id=4),
        QualityRule(match=["2160p"], target_id=13),
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        quality_profiles=[{"id": 6, "name": "Web-DL 1080p"}],
        quality_definitions=[{"id": 4, "name": "HDTV-1080p"}, {"id": 13, "name": "Bluray-2160p"}],
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr quality profiles (id:name):" in caplog.text
    assert "6:Web-DL 1080p" in caplog.text
    assert "Radarr quality definitions (id:name):" in caplog.text
    assert "4:HDTV-1080p" in caplog.text
    assert "13:Bluray-2160p" in caplog.text
    assert "radarr.mapping.quality_map target_id values validated" in caplog.text


def test_sync_preflight_warns_when_quality_target_id_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.quality_map = [QualityRule(match=["2160p"], target_id=99)]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(quality_definitions=[{"id": 4, "name": "HDTV-1080p"}])

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "radarr.mapping.quality_map target_id values not found" in caplog.text
    assert "missing_ids=[99]" in caplog.text


def test_sync_preflight_parses_nested_quality_definition_shape(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.quality_map = [QualityRule(match=["1080p"], target_id=4)]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        quality_definitions=[
            {"id": 901, "quality": {"id": 4, "name": "HDTV-1080p"}},
            {"id": 902, "quality": {"id": 13, "name": "Bluray-2160p"}},
        ]
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr quality definitions (id:name):" in caplog.text
    assert "4:HDTV-1080p" in caplog.text
    assert "13:Bluray-2160p" in caplog.text
    assert "radarr.mapping.quality_map target_id values validated" in caplog.text


def test_sync_preflight_logs_custom_format_catalog_and_validation(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.custom_format_map = [
        CustomFormatRule(match=["german"], format_id=42),
        CustomFormatRule(match=["x265"], format_id=99),
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        custom_formats=[
            {"id": 42, "name": "German Audio"},
            {"id": 99, "name": "HEVC"},
        ]
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert (
        "radarr.mapping.custom_format_map contains format ids for local analysis fallback: [42, 99]"
        in caplog.text
    )
    assert "Radarr custom formats (id:name):" in caplog.text
    assert "42:German Audio" in caplog.text
    assert "99:HEVC" in caplog.text
    assert "radarr.mapping.custom_format_map format_id values validated" in caplog.text


def test_sync_preflight_warns_when_custom_format_id_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.custom_format_map = [CustomFormatRule(match=["german"], format_id=999)]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(custom_formats=[{"id": 42, "name": "German Audio"}])

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "radarr.mapping.custom_format_map format_id values not found" in caplog.text
    assert "missing_ids=[999]" in caplog.text


def test_arr_history_safety_poll_queues_both_radarr_and_sonarr(tmp_path: Path, monkeypatch) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.sonarr.enabled = True
    config.sonarr.sync_enabled = True
    config.sonarr.url = "http://sonarr:8989"
    config.sonarr.api_key = "test"
    config.runtime.arr_event_safety_poll_interval_minutes = 1
    config.runtime.arr_event_safety_bootstrap_lookback_minutes = 60

    service = LibrariArrService(config)
    service.radarr = _FakeRadarrWithHistory(
        [{"id": 11, "date": "2025-01-01T01:00:00Z", "movieId": 101, "eventType": "download"}]
    )
    service.sonarr = _FakeSonarr(
        [{"id": 22, "date": "2025-01-01T01:00:00Z", "seriesId": 202, "eventType": "grabbed"}]
    )

    radarr_queue = get_radarr_webhook_queue()
    sonarr_queue = get_sonarr_webhook_queue()
    radarr_queue.consume_movie_ids()
    sonarr_queue.consume_series_ids()

    monkeypatch.setattr("librariarr.service.preflight.time.time", lambda: 1735696800.0)

    assert service._poll_arr_root_reconcile_trigger() is True

    assert radarr_queue.consume_movie_ids() == {101}
    assert sonarr_queue.consume_series_ids() == {202}


def test_arr_history_safety_poll_bootstrap_without_lookback_only_sets_cursor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.runtime.arr_event_safety_poll_interval_minutes = 1
    config.runtime.arr_event_safety_bootstrap_lookback_minutes = 0

    service = LibrariArrService(config)
    history_records = [{"id": 50, "date": "2025-01-01T01:00:00Z", "movieId": 42}]
    service.radarr = _FakeRadarrWithHistory(history_records)

    radarr_queue = get_radarr_webhook_queue()
    radarr_queue.consume_movie_ids()

    now = {"value": 1735696800.0}
    monkeypatch.setattr("librariarr.service.preflight.time.time", lambda: now["value"])

    assert service._poll_arr_root_reconcile_trigger() is False
    assert radarr_queue.consume_movie_ids() == set()
    assert service._radarr_event_safety_cursor_id == 50

    service.radarr.history_records.append({"id": 51, "date": "2025-01-01T01:02:00Z", "movieId": 43})
    now["value"] += 61.0
    assert service._poll_arr_root_reconcile_trigger() is True

    assert radarr_queue.consume_movie_ids() == {43}
