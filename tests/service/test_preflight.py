from pathlib import Path

import requests

from librariarr.config import CustomFormatRule, QualityRule
from librariarr.service import LibrariArrService
from tests.service.helpers import FakeRadarr, make_config


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
        QualityRule(match=["1080p"], target_id=4, name="HDTV-1080p"),
        QualityRule(match=["2160p"], target_id=13, name="4K"),
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        quality_profiles=[{"id": 6, "name": "Web-DL 1080p"}],
        quality_definitions=[{"id": 4, "name": "HDTV-1080p"}, {"id": 13, "name": "Bluray-2160p"}],
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr quality profiles (id:name): 6:Web-DL 1080p" in caplog.text
    assert "Radarr quality definitions (id:name): 4:HDTV-1080p, 13:Bluray-2160p" in caplog.text
    assert "radarr.mapping.quality_map target_id values validated" in caplog.text


def test_sync_preflight_warns_when_quality_target_id_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.quality_map = [QualityRule(match=["2160p"], target_id=99, name="Missing")]
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
    config.radarr.mapping.quality_map = [
        QualityRule(match=["1080p"], target_id=4, name="HDTV-1080p")
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(
        quality_definitions=[
            {"id": 901, "quality": {"id": 4, "name": "HDTV-1080p"}},
            {"id": 902, "quality": {"id": 13, "name": "Bluray-2160p"}},
        ]
    )

    caplog.set_level("INFO", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "Radarr quality definitions (id:name): 4:HDTV-1080p, 13:Bluray-2160p" in caplog.text
    assert "radarr.mapping.quality_map target_id values validated" in caplog.text


def test_sync_preflight_logs_custom_format_catalog_and_validation(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.custom_format_map = [
        CustomFormatRule(match=["german"], format_id=42, name="German Audio"),
        CustomFormatRule(match=["x265"], format_id=99, name="HEVC"),
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
    assert "Radarr custom formats (id:name): 42:German Audio, 99:HEVC" in caplog.text
    assert "radarr.mapping.custom_format_map format_id values validated" in caplog.text


def test_sync_preflight_warns_when_custom_format_id_missing(tmp_path: Path, caplog) -> None:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "radarr_library"
    nested_root.mkdir(parents=True)

    config = make_config(nested_root, shadow_root, sync_enabled=True)
    config.radarr.mapping.custom_format_map = [
        CustomFormatRule(match=["german"], format_id=999, name="Missing")
    ]
    service = LibrariArrService(config)
    service.radarr = FakeRadarr(custom_formats=[{"id": 42, "name": "German Audio"}])

    caplog.set_level("WARNING", logger="librariarr.service")
    service._run_sync_preflight_checks()

    assert "radarr.mapping.custom_format_map format_id values not found" in caplog.text
    assert "missing_ids=[999]" in caplog.text
