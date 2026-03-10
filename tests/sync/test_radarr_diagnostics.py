import logging
from pathlib import Path

from librariarr.config import (
    AppConfig,
    CleanupConfig,
    CustomFormatRule,
    PathsConfig,
    QualityRule,
    RadarrConfig,
    RootMapping,
    RuntimeConfig,
)
from librariarr.sync.radarr_diagnostics import log_quality_mapping_diagnostics


class FakeRadarr:
    def __init__(
        self,
        *,
        quality_profiles: list[dict] | None = None,
        quality_definitions: list[dict] | None = None,
        custom_formats: list[dict] | None = None,
    ) -> None:
        self.quality_profiles = quality_profiles or []
        self.quality_definitions = quality_definitions or []
        self.custom_formats = custom_formats or []

    def get_quality_profiles(self) -> list[dict]:
        return self.quality_profiles

    def get_quality_definitions(self) -> list[dict]:
        return self.quality_definitions

    def get_custom_formats(self) -> list[dict]:
        return self.custom_formats


def _make_config(tmp_path: Path, quality_id: int, format_id: int) -> AppConfig:
    nested_root = tmp_path / "nested"
    shadow_root = tmp_path / "shadow"
    nested_root.mkdir(parents=True, exist_ok=True)
    shadow_root.mkdir(parents=True, exist_ok=True)

    return AppConfig(
        paths=PathsConfig(
            root_mappings=[
                RootMapping(
                    nested_root=str(nested_root),
                    shadow_root=str(shadow_root),
                )
            ]
        ),
        radarr=RadarrConfig(
            url="http://radarr:7878",
            api_key="test-key",
            sync_enabled=True,
            auto_add_unmatched=True,
        ),
        quality_map=[QualityRule(match=["1080p"], target_id=quality_id, name="1080p")],
        custom_format_map=[
            CustomFormatRule(match=["german"], format_id=format_id, name="German Audio")
        ],
        cleanup=CleanupConfig(),
        runtime=RuntimeConfig(),
    )


def test_log_quality_mapping_diagnostics_logs_validation_success(tmp_path: Path, caplog) -> None:
    config = _make_config(tmp_path, quality_id=7, format_id=42)
    fake = FakeRadarr(
        quality_profiles=[{"id": 8, "name": "Preferred"}],
        quality_definitions=[{"quality": {"id": 7, "name": "Bluray-1080p"}}],
        custom_formats=[{"id": 42, "name": "German Audio"}],
    )

    caplog.set_level("INFO")
    log_quality_mapping_diagnostics(
        config=config,
        log=logging.getLogger(__name__),
        radarr=fake,
        auto_add_unmatched=True,
    )

    assert "Radarr quality profiles (id:name): 8:Preferred" in caplog.text
    assert "quality_map target_id values validated" in caplog.text
    assert "custom_format_map format_id values validated" in caplog.text


def test_log_quality_mapping_diagnostics_warns_on_missing_ids(tmp_path: Path, caplog) -> None:
    config = _make_config(tmp_path, quality_id=999, format_id=555)
    fake = FakeRadarr(
        quality_profiles=[{"id": 8, "name": "Preferred"}],
        quality_definitions=[{"quality": {"id": 7, "name": "Bluray-1080p"}}],
        custom_formats=[{"id": 42, "name": "German Audio"}],
    )

    caplog.set_level("WARNING")
    log_quality_mapping_diagnostics(
        config=config,
        log=logging.getLogger(__name__),
        radarr=fake,
        auto_add_unmatched=True,
    )

    assert "quality_map target_id values not found" in caplog.text
    assert "missing_ids=[999]" in caplog.text
    assert "custom_format_map format_id values not found" in caplog.text
    assert "missing_ids=[555]" in caplog.text
