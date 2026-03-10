from pathlib import Path
from unittest.mock import patch

from librariarr.config import CustomFormatRule, QualityRule
from librariarr.quality import collect_media_probe_text, map_custom_format_ids, map_quality_id


def test_map_quality_id_matches_and_rule(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Fixture Catalog A (2008)"
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


def test_collect_media_probe_text_extracts_extended_tokens(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Demo (2024)"
    movie_dir.mkdir()
    (movie_dir / "Demo.2024.mkv").write_text("x", encoding="utf-8")

    probe_json = (
        '{"streams":['
        '{"codec_type":"video","height":2160,"codec_name":"hevc","bit_rate":"32000000","color_transfer":"smpte2084"},'
        '{"codec_type":"audio","codec_name":"truehd","channels":8}'
        "]}"
    )

    with patch("subprocess.check_output", return_value=probe_json):
        text = collect_media_probe_text(movie_dir)

    assert "2160p" in text
    assert "x265" in text
    assert "hevc" in text
    assert "hdr10" in text
    assert "remux-bitrate" in text
    assert "truehd" in text
    assert "7.1" in text


def test_collect_media_probe_text_extracts_audio_language_tokens(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Lang Demo (2024)"
    movie_dir.mkdir()
    (movie_dir / "Lang.Demo.2024.mkv").write_text("x", encoding="utf-8")

    probe_json = (
        '{"streams":['
        '{"codec_type":"video","height":1080,"codec_name":"hevc"},'
        '{"codec_type":"audio","codec_name":"ac3","channels":6,"tags":{"language":"deu"}},'
        '{"codec_type":"audio","codec_name":"aac","channels":2,"tags":{"language":"eng"}}'
        "]}"
    )

    with patch("subprocess.check_output", return_value=probe_json):
        text = collect_media_probe_text(movie_dir)

    assert "german" in text
    assert "english" in text
    assert "lang-de" in text
    assert "lang-en" in text
    assert "multi-language" in text
    assert "dual-language" in text


def test_map_quality_id_uses_larger_non_sample_video_for_probe(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Demo (2024)"
    movie_dir.mkdir()
    sample = movie_dir / "Demo.sample.mkv"
    sample.write_text("tiny", encoding="utf-8")
    main = movie_dir / "Demo.2024.main.mkv"
    main.write_text("x" * 2000, encoding="utf-8")

    rules = [QualityRule(match=["2160p", "x265"], target_id=13, name="4K Bluray")]

    def _fake_probe(cmd: list[str], stderr=None, text=True, timeout=5):  # type: ignore[override]
        file_name = Path(cmd[-1]).name.lower()
        if "sample" in file_name:
            return '{"streams":[{"codec_type":"video","height":720,"codec_name":"h264"}]}'
        return '{"streams":[{"codec_type":"video","height":2160,"codec_name":"hevc"}]}'

    with patch("subprocess.check_output", side_effect=_fake_probe):
        result = map_quality_id(movie_dir, rules, default_id=4, use_media_probe=True)

    assert result == 13


def test_map_quality_id_treats_x265_h265_hevc_as_equivalent(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Codec Demo (2024)"
    movie_dir.mkdir()
    (movie_dir / "Codec.Demo.2024.1080p.h265.mkv").write_text("x", encoding="utf-8")

    rules = [QualityRule(match=["1080p", "x265"], target_id=7, name="Bluray-1080p")]

    assert map_quality_id(movie_dir, rules, default_id=4) == 7


def test_map_quality_id_treats_x264_h264_avc_as_equivalent(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Codec Demo AVC (2024)"
    movie_dir.mkdir()
    (movie_dir / "Codec.Demo.AVC.2024.1080p.mkv").write_text("x", encoding="utf-8")

    rules = [QualityRule(match=["1080p", "h264"], target_id=9, name="HDTV-1080p")]

    assert map_quality_id(movie_dir, rules, default_id=4) == 9


def test_map_custom_format_ids_uses_nfo_and_probe_tokens(tmp_path: Path) -> None:
    movie_dir = tmp_path / "Custom Format Demo (2024)"
    movie_dir.mkdir()
    (movie_dir / "Custom.Format.Demo.2024.mkv").write_text("x", encoding="utf-8")
    (movie_dir / "movie.nfo").write_text("language: german", encoding="utf-8")

    rules = [
        CustomFormatRule(match=["german"], format_id=42, name="German"),
        CustomFormatRule(match=["2160p", "hevc"], format_id=99, name="4K HEVC"),
    ]
    probe_json = '{"streams":[{"codec_type":"video","height":2160,"codec_name":"hevc"}]}'

    with patch("subprocess.check_output", return_value=probe_json):
        matched = map_custom_format_ids(
            movie_dir,
            rules,
            use_nfo=True,
            use_media_probe=True,
        )

    assert matched == {42, 99}
