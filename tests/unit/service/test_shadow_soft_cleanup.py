from __future__ import annotations

from pathlib import Path

from librariarr.service.reconcile_helpers import run_stale_shadow_cleanup


class _FakeStateStore:
    def __init__(self, rows: list[tuple[int, str, str, int | None, int | None]]) -> None:
        self._rows = rows

    def list_managed_projected_rows(
        self,
        *,
        movie_ids: set[int] | None = None,
    ) -> list[tuple[int, str, str, int | None, int | None]]:
        if movie_ids is None:
            return list(self._rows)
        return [row for row in self._rows if row[0] in movie_ids]


class _FakeProjection:
    def __init__(self, rows: list[tuple[int, str, str, int | None, int | None]]) -> None:
        self.state_store = _FakeStateStore(rows)

    def cleanup_stale_shadow(self, *, candidate_ids: set[int], affected_targets: set[Path] | None):
        _ = candidate_ids
        _ = affected_targets
        return {"removed_files": 0, "pruned_rows": 0, "skipped_candidates": 0}


def _write(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")


def test_soft_deletes_unmanaged_shadow_videos_in_tracked_parent(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    shadow_root = tmp_path / "shadow" / ".librariarr"
    tracked = shadow_root / "Ich bin Sam (2001)" / "tracked.mkv"
    stale_untracked = shadow_root / "Ich bin Sam (2001)" / "old-untracked.mkv"
    unrelated_untracked = shadow_root / "Other Movie (2004)" / "unknown.mkv"

    _write(tracked)
    _write(stale_untracked)
    _write(unrelated_untracked)

    projection = _FakeProjection(
        [
            (
                1,
                str(tracked),
                str(managed_root / "Ich bin Sam (2001)" / "tracked.mkv"),
                1,
                1,
            )
        ]
    )

    removed = run_stale_shadow_cleanup(
        reconcile_mode="full",
        affected_paths=None,
        movie_root_mappings=[(managed_root, shadow_root)],
        series_root_mappings=[],
        movie_projection_metrics={"matched_movie_ids": {1}, "matched_movie_ids_count": 1},
        series_projection_metrics={"matched_series_ids": set()},
        video_exts={".mkv"},
        radarr_enabled=True,
        sonarr_enabled=False,
        movie_projection=projection,
        sonarr_projection=None,
    )

    assert removed == 1
    assert tracked.exists()
    assert not stale_untracked.exists()
    assert unrelated_untracked.exists()

    recycle_dir = shadow_root / ".deletedByLibrariarr" / "Ich bin Sam (2001)"
    recycled = list(recycle_dir.glob("old-untracked.mkv.*"))
    assert len(recycled) == 1


def test_does_not_soft_delete_when_no_tracked_projection_parent(tmp_path: Path) -> None:
    managed_root = tmp_path / "managed"
    shadow_root = tmp_path / "shadow" / ".librariarr"
    candidate = shadow_root / "Lonely Movie (2001)" / "stray.mkv"
    _write(candidate)

    projection = _FakeProjection([])
    removed = run_stale_shadow_cleanup(
        reconcile_mode="full",
        affected_paths=None,
        movie_root_mappings=[(managed_root, shadow_root)],
        series_root_mappings=[],
        movie_projection_metrics={"matched_movie_ids": {1}},
        series_projection_metrics={"matched_series_ids": set()},
        video_exts={".mkv"},
        radarr_enabled=True,
        sonarr_enabled=False,
        movie_projection=projection,
        sonarr_projection=None,
    )

    assert removed == 0
    assert candidate.exists()
