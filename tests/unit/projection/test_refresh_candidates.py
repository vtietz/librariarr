from librariarr.projection.orchestrator import _refresh_candidate_movie_ids
from librariarr.projection.sonarr_orchestrator import _refresh_candidate_series_ids


def test_movie_refresh_candidates_use_scoped_ids_when_present() -> None:
    candidates = _refresh_candidate_movie_ids(
        scoped_movie_ids={101, 202},
        projected_movie_ids={202, 303},
    )

    assert candidates == {101, 202}


def test_movie_refresh_candidates_use_projected_ids_when_full_reconcile() -> None:
    candidates = _refresh_candidate_movie_ids(
        scoped_movie_ids=None,
        projected_movie_ids={7, 8},
    )

    assert candidates == {7, 8}


def test_series_refresh_candidates_use_scoped_ids_when_present() -> None:
    candidates = _refresh_candidate_series_ids(
        scoped_series_ids={11, 12},
        projected_series_ids={12, 13},
    )

    assert candidates == {11, 12}


def test_series_refresh_candidates_use_projected_ids_when_full_reconcile() -> None:
    candidates = _refresh_candidate_series_ids(
        scoped_series_ids=None,
        projected_series_ids={21, 22},
    )

    assert candidates == {21, 22}
