from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from librariarr.config.models import RuntimeConfig
from librariarr.runtime.daily import DailySchedule


def ts(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp()


class Clock:
    def __init__(self, start: str) -> None:
        self.now = ts(start)

    def __call__(self) -> float:
        return self.now

    def set(self, text: str) -> None:
        self.now = ts(text)


def make(clock: Clock, state_path: Path | None = None, **overrides) -> DailySchedule:
    config = RuntimeConfig(
        schedule_mode="daily",
        daily_full_time=overrides.pop("time", "03:00"),
        daily_timezone=overrides.pop("tz", "UTC"),
        daily_retry_minutes=overrides.pop("retry", 60),
    )
    return DailySchedule(config, state_path=state_path, clock=clock, **overrides)


def test_restart_outside_the_slot_does_not_run_and_waits_for_next_slot(tmp_path: Path):
    clock = Clock("2026-11-19T12:00:00")
    schedule = make(clock, tmp_path / "s.json")
    assert schedule.slot_due(clock()) is None
    assert schedule.due_at(clock()) == ts("2026-11-20T03:00:00")


def test_slot_reached_while_running_is_due_once(tmp_path: Path):
    clock = Clock("2026-11-19T02:59:00")
    schedule = make(clock, tmp_path / "s.json")
    assert schedule.slot_due(clock()) is None
    clock.set("2026-11-19T03:00:00")
    assert schedule.slot_due(clock()) == "2026-11-19"
    schedule.record("2026-11-19", ok=True)
    assert schedule.slot_due(clock()) is None
    assert schedule.due_at(clock()) == ts("2026-11-20T03:00:00")


def test_successful_slot_is_not_repeated_after_restart(tmp_path: Path):
    state = tmp_path / "s.json"
    clock = Clock("2026-11-19T02:59:00")
    first = make(clock, state)
    clock.set("2026-11-19T03:00:30")
    first.record(first.slot_due(clock()), ok=True)

    clock.set("2026-11-19T03:05:00")
    second = make(clock, state)
    assert second.slot_due(clock()) is None
    assert second.snapshot()["missed_slot"] is None
    assert second.snapshot()["last_success_slot"] == "2026-11-19"


def test_missed_slot_is_reported_but_not_caught_up(tmp_path: Path):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"last_success_slot": "2026-11-17", "last_result": "ok"}))
    clock = Clock("2026-11-19T10:00:00")
    schedule = make(clock, state)
    snap = schedule.snapshot()
    assert snap["missed_slot"] == "2026-11-19"
    assert schedule.slot_due(clock()) is None
    assert snap["next_run_at"] == ts("2026-11-20T03:00:00")


def test_first_start_without_state_reports_nothing_missed(tmp_path: Path):
    clock = Clock("2026-11-19T10:00:00")
    assert make(clock, tmp_path / "s.json").snapshot()["missed_slot"] is None


def test_failure_schedules_a_bounded_retry_and_publishes(tmp_path: Path):
    published: list[dict] = []
    clock = Clock("2026-11-19T02:59:00")
    schedule = make(clock, tmp_path / "s.json", on_change=published.append)
    clock.set("2026-11-19T03:00:00")
    schedule.record("2026-11-19", ok=False, error="radarr: boom")

    snap = published[-1]
    assert snap["last_result"] == "failed"
    assert snap["last_error"] == "radarr: boom"
    assert snap["retry_at"] == ts("2026-11-19T04:00:00")
    assert snap["consecutive_failures"] == 1
    # Not due again until the retry time: no tight loop.
    clock.set("2026-11-19T03:30:00")
    assert schedule.slot_due(clock()) is None
    clock.set("2026-11-19T04:00:00")
    assert schedule.slot_due(clock()) == "2026-11-19"
    schedule.record("2026-11-19", ok=True)
    assert published[-1]["last_result"] == "ok"
    assert published[-1]["consecutive_failures"] == 0


def test_retry_never_runs_past_the_next_slot(tmp_path: Path):
    clock = Clock("2026-11-19T02:00:00")
    schedule = make(clock, tmp_path / "s.json", time="02:30")
    clock.set("2026-11-20T02:00:00")  # slot 2026-11-19 is current; next slot in 30 min
    schedule.record("2026-11-19", ok=False, error="x")
    assert schedule.snapshot()["retry_at"] is None
    assert schedule.due_at(clock()) == ts("2026-11-20T02:30:00")


def test_pending_retry_survives_restart(tmp_path: Path):
    state = tmp_path / "s.json"
    clock = Clock("2026-11-19T02:59:00")
    first = make(clock, state)
    clock.set("2026-11-19T03:00:00")
    first.record("2026-11-19", ok=False, error="boom")

    clock.set("2026-11-19T03:10:00")
    second = make(clock, state)
    assert second.snapshot()["missed_slot"] is None
    assert second.due_at(clock()) == ts("2026-11-19T04:00:00")


def test_slot_follows_configured_timezone(tmp_path: Path):
    # 03:00 Europe/Berlin in November (CET, UTC+1) is 02:00 UTC.
    clock = Clock("2026-11-19T01:00:00")
    schedule = make(clock, tmp_path / "s.json", tz="Europe/Berlin")
    assert schedule.due_at(clock()) == ts("2026-11-19T02:00:00")


def test_unreadable_state_is_ignored(tmp_path: Path):
    state = tmp_path / "s.json"
    state.write_text("{not json")
    clock = Clock("2026-11-19T10:00:00")
    assert make(clock, state).snapshot()["last_success_slot"] is None


def test_malformed_state_fields_are_dropped_not_fatal(tmp_path: Path):
    state = tmp_path / "s.json"
    state.write_text(
        json.dumps(
            {
                "consecutive_failures": "invalid",
                "retry_at": "soon",
                "last_attempt_slot": "2026-11-19",
                "last_success_slot": 42,
                "last_result": "maybe",
                "last_error": ["x"],
                "last_attempt_at": True,
            }
        )
    )
    clock = Clock("2026-11-19T10:00:00")
    schedule = make(clock, state)  # must not raise
    snap = schedule.snapshot()
    assert snap["consecutive_failures"] == 0
    assert snap["retry_at"] is None
    assert snap["last_success_slot"] is None
    assert snap["last_result"] is None
    assert snap["last_attempt_slot"] == "2026-11-19"
    # Attempted slot without a usable retry: wait for the next slot, no tight loop.
    assert schedule.due_at(clock()) == ts("2026-11-20T03:00:00")


def test_non_object_state_is_ignored(tmp_path: Path):
    state = tmp_path / "s.json"
    state.write_text("[1, 2]")
    clock = Clock("2026-11-19T10:00:00")
    assert make(clock, state).snapshot()["last_success_slot"] is None
