import subprocess
import sys
from pathlib import Path


def test_main_no_longer_fails_fast_for_ambiguous_ingest_root_mappings(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        (
            "paths:\n"
            "  series_root_mappings:\n"
            "    - nested_root: /data/movies/a\n"
            "      shadow_root: /data/radarr_library\n"
            "    - nested_root: /data/movies/b\n"
            "      shadow_root: /data/radarr_library\n"
            "  movie_root_mappings:\n"
            "    - managed_root: /data/movies/a\n"
            "      library_root: /data/radarr_library\n"
            "radarr:\n"
            "  url: http://radarr:7878\n"
            "  api_key: test-key\n"
            "  enabled: false\n"
            "  sync_enabled: false\n"
            "cleanup: {}\n"
            "runtime: {}\n"
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

    assert proc.returncode == 0
