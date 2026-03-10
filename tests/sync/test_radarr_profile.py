from librariarr.sync.radarr_profile import (
    score_profile_for_custom_formats,
    score_profile_for_quality,
)


def test_score_profile_for_quality_prefers_cutoff_exact() -> None:
    profile = {
        "id": 7,
        "name": "Exact",
        "cutoff": {"id": 7},
        "items": [{"quality": {"id": 7}, "allowed": True}],
    }

    ranked = score_profile_for_quality(profile, desired_quality_id=7, rank_map={7: 1})

    assert ranked is not None
    score, reason = ranked
    assert reason == "cutoff_exact"
    assert score[0] == 0


def test_score_profile_for_quality_returns_none_when_disallowed() -> None:
    profile = {
        "id": 7,
        "name": "Profile",
        "items": [{"quality": {"id": 7}, "allowed": False}],
    }

    ranked = score_profile_for_quality(profile, desired_quality_id=7, rank_map={7: 1})

    assert ranked is None


def test_score_profile_for_custom_formats_prefers_higher_score() -> None:
    profile = {
        "id": 7,
        "name": "Specific",
        "minFormatScore": 50,
        "formatItems": [
            {"format": 42, "score": 60},
            {"format": 99, "score": 40},
        ],
    }

    ranked = score_profile_for_custom_formats(profile, custom_format_ids={42})

    assert ranked is not None
    score, reason = ranked
    assert reason == "custom_formats"
    assert score[0] == 0


def test_score_profile_for_custom_formats_returns_none_without_matches() -> None:
    profile = {
        "id": 7,
        "name": "Specific",
        "formatItems": [{"format": 42, "score": 10}],
    }

    ranked = score_profile_for_custom_formats(profile, custom_format_ids={99})

    assert ranked is None
