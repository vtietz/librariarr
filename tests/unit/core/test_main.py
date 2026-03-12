import subprocess
import sys
from pathlib import Path


def test_main_fails_fast_for_ambiguous_ingest_root_mappings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  root_mappings:\n"
            "    - nested_root: /data/movies/a\n"
            "      shadow_root: /data/radarr_library\n"
            "    - nested_root: /data/movies/b\n"
            "      shadow_root: /data/radarr_library\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  sync_enabled: false\n"
            "cleanup: {}\n"
            "runtime: {}\n"
            "ingest:\n"
            "  enabled: true\n"
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "librariarr.main",
            "--config",
            str(config_path),
            "--once",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode != 0
    combined_output = f"{proc.stdout}\n{proc.stderr}"
    assert "Ingest requires a 1:1 mapping" in combined_output
