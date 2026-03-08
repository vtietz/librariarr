from pathlib import Path
from unittest.mock import patch

from librariarr.config import QualityRule
from librariarr.quality import map_quality_id


def test_map_quality_id_matches_and_rule(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Big Buck Bunny (2008)"
    movie_dir.mkdir()
    (movie_dir / "Big.Buck.Bunny.2008.1080p.x265.mkv").write_text("x", encoding="utf-8")

    rules = [
        QualityRule(match=["2160p"], target_id=13, name="4K Bluray"),
        QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p"),
    ]

    assert map_quality_id(movie_dir, rules, default_id=4) == 7


def test_map_quality_id_uses_default_when_no_rule_matches(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Sintel (2010)"
    movie_dir.mkdir()
    (movie_dir / "Sintel.2010.DVDRip.avi").write_text("x", encoding="utf-8")

    rules = [QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")]

    assert map_quality_id(movie_dir, rules, default_id=4) == 4


def test_map_quality_id_uses_nfo_fallback_when_enabled(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Tears of Steel (2012)"
    movie_dir.mkdir()
    (movie_dir / "Tears.Of.Steel.2012.mkv").write_text("x", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text("Video: 1080p HEVC", encoding="utf-8")

    rules = [QualityRule(match=["1080p", "hevc"], target_id=7, name="Bluray-1080p")]

    assert map_quality_id(movie_dir, rules, default_id=4, use_nfo=True) == 7


def test_map_quality_id_uses_media_probe_fallback_when_enabled(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Sintel (2010)"
    movie_dir.mkdir()
    (movie_dir / "Sintel.2010.mkv").write_text("x", encoding="utf-8")

    rules = [QualityRule(match=["2160p", "x265"], target_id=13, name="4K Bluray")]
    probe_json = '{"streams":[{"height":2160,"codec_name":"hevc"}]}'

    with patch("subprocess.check_output", return_value=probe_json):
        result = map_quality_id(movie_dir, rules, default_id=4, use_media_probe=True)

    assert result == 13
