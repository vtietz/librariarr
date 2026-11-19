"""Daily full-pass schedule (``runtime.schedule_mode: daily``).

One full pass per local calendar day at ``daily_full_time``. The slot a run
belongs to is identified by its local date, persisted in a small JSON marker so
a restart never repeats a slot that already succeeded. Rules:

- A slot that comes due while the process is running runs at once.
- A slot that passed while the process was down is reported as *missed* and is
  not caught up on startup: a restart outside the schedule must not walk the
  tree. The next slot covers it.
- A failed run (exception, or a report carrying errors) is retried after
  ``daily_retry_minutes``, but never past the next slot, which supersedes it. A
  pending retry survives a restart.

The marker is advisory like the id cache: deleting it only loses the
duplicate-run guard and the last-result display.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..config.loader import parse_daily_time
from ..config.models import RuntimeConfig

LOG = logging.getLogger(__name__)

RESULT_OK = "ok"
RESULT_FAILED = "failed"


def resolve_timezone(name: str):
    """Configured IANA zone, else the process-local zone: ``TZ``, then
    ``/etc/localtime`` (both DST-aware), then the current fixed offset."""
    if name:
        return ZoneInfo(name)
    env_tz = os.getenv("TZ", "").strip().lstrip(":")
    if env_tz:
        try:
            return ZoneInfo(env_tz)
        except (ZoneInfoNotFoundError, ValueError):
            LOG.warning("TZ=%s is not a known zone; falling back to /etc/localtime", env_tz)
    try:
        with open("/etc/localtime", "rb") as fh:
            return ZoneInfo.from_file(fh, key="localtime")
    except (OSError, ValueError):
        return datetime.now().astimezone().tzinfo


class DailySchedule:
    def __init__(
        self,
        config: RuntimeConfig,
        *,
        state_path: Path | None = None,
        clock: Callable[[], float] = time.time,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._time = parse_daily_time(config.daily_full_time)
        self._time_text = config.daily_full_time
        self._tz = resolve_timezone(config.daily_timezone)
        self._tz_name = config.daily_timezone or str(self._tz)
        self._retry_seconds = max(60, int(config.daily_retry_minutes) * 60)
        self._state_path = state_path
        self._clock = clock
        self._on_change = on_change
        self._started_at = clock()
        self._state: dict[str, Any] = self._load()
        self._missed_slot: str | None = None
        self._detect_missed()
        self._publish()

    # -- slot arithmetic --------------------------------------------------

    def _slot_ts(self, day: date) -> float:
        return datetime.combine(day, self._time, tzinfo=self._tz).timestamp()

    def current_slot(self, now: float) -> tuple[str, float]:
        """The most recent slot at or before ``now``: (local date, epoch)."""
        today = datetime.fromtimestamp(now, self._tz).date()
        for day in (today, today - timedelta(days=1)):
            ts = self._slot_ts(day)
            if ts <= now:
                return day.isoformat(), ts
        day = today - timedelta(days=2)  # only reachable across odd DST edges
        return day.isoformat(), self._slot_ts(day)

    def next_slot_after(self, now: float) -> float:
        today = datetime.fromtimestamp(now, self._tz).date()
        for offset in range(3):
            ts = self._slot_ts(today + timedelta(days=offset))
            if ts > now:
                return ts
        return now + 86400

    # -- decisions --------------------------------------------------------

    def due_at(self, now: float) -> float:
        """Epoch at which the next daily run should start (may be <= now)."""
        slot, slot_ts = self.current_slot(now)
        state = self._state
        if state.get("last_success_slot") == slot:
            return self.next_slot_after(now)
        if state.get("last_attempt_slot") == slot:
            retry_at = state.get("retry_at")
            return float(retry_at) if retry_at is not None else self.next_slot_after(now)
        if slot_ts >= self._started_at:
            return slot_ts
        # The slot passed before this process started: missed, not caught up.
        return self.next_slot_after(now)

    def slot_due(self, now: float) -> str | None:
        return self.current_slot(now)[0] if self.due_at(now) <= now else None

    def record(self, slot: str, *, ok: bool, error: str | None = None) -> None:
        now = self._clock()
        state = self._state
        state["last_attempt_slot"] = slot
        state["last_attempt_at"] = now
        if ok:
            state["last_success_slot"] = slot
            state["last_success_at"] = now
            state["last_result"] = RESULT_OK
            state["last_error"] = None
            state["retry_at"] = None
            state["consecutive_failures"] = 0
            self._missed_slot = None
        else:
            retry_at = now + self._retry_seconds
            if retry_at >= self.next_slot_after(now):
                retry_at = None  # the next slot supersedes the retry
            state["last_result"] = RESULT_FAILED
            state["last_error"] = error or "unknown error"
            state["retry_at"] = retry_at
            state["consecutive_failures"] = int(state.get("consecutive_failures") or 0) + 1
            LOG.error(
                "Daily full pass for %s failed: %s; %s",
                slot,
                state["last_error"],
                f"retrying at {_fmt(retry_at, self._tz)}"
                if retry_at
                else "next attempt at the next scheduled slot",
            )
        self._save()
        self._publish()

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        state = self._state
        return {
            "mode": "daily",
            "time": self._time_text,
            "timezone": self._tz_name,
            "next_run_at": self.due_at(now),
            "last_success_slot": state.get("last_success_slot"),
            "last_success_at": state.get("last_success_at"),
            "last_attempt_slot": state.get("last_attempt_slot"),
            "last_attempt_at": state.get("last_attempt_at"),
            "last_result": state.get("last_result"),
            "last_error": state.get("last_error"),
            "retry_at": state.get("retry_at"),
            "consecutive_failures": int(state.get("consecutive_failures") or 0),
            "missed_slot": self._missed_slot,
        }

    # -- internals --------------------------------------------------------

    def _detect_missed(self) -> None:
        if not self._state:
            return  # first start ever: nothing could have been missed
        slot, _ = self.current_slot(self._started_at)
        state = self._state
        if state.get("last_success_slot") == slot:
            return
        if state.get("last_attempt_slot") == slot and state.get("retry_at") is not None:
            return  # a failed slot with a pending retry is still in progress
        self._missed_slot = slot
        LOG.warning(
            "Daily full pass for %s did not complete (last success: %s); "
            "not catching up on startup, next run at %s",
            slot,
            state.get("last_success_slot") or "never",
            _fmt(self.next_slot_after(self._started_at), self._tz),
        )

    def _load(self) -> dict[str, Any]:
        if self._state_path is None or not self._state_path.exists():
            return {}
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            LOG.warning("Ignoring unreadable schedule state %s: %s", self._state_path, exc)
            return {}
        if not isinstance(data, dict):
            LOG.warning("Ignoring malformed schedule state %s", self._state_path)
            return {}
        return self._sanitize(data)

    def _sanitize(self, data: dict[str, Any]) -> dict[str, Any]:
        """Keep only well-typed fields: the marker is advisory, so a bad value
        must degrade to "unknown", never stop the loop from starting."""
        clean: dict[str, Any] = {}
        dropped: list[str] = []
        for key, value in data.items():
            check = _FIELD_CHECKS.get(key)
            if check is None:
                continue  # unknown keys are ignored silently (forward compat)
            if value is None or check(value):
                clean[key] = value
            else:
                dropped.append(key)
        if dropped:
            LOG.warning(
                "Ignoring invalid fields in schedule state %s: %s",
                self._state_path,
                ", ".join(sorted(dropped)),
            )
        return clean

    def _save(self) -> None:
        if self._state_path is None:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._state_path.parent, prefix=".schedule-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._state, fh, indent=2, sort_keys=True)
            os.replace(tmp, self._state_path)
        except OSError as exc:
            LOG.warning("Could not persist schedule state %s: %s", self._state_path, exc)

    def _publish(self) -> None:
        if self._on_change is not None:
            self._on_change(self.snapshot())


def _is_slot(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _is_timestamp(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


_FIELD_CHECKS: dict[str, Callable[[Any], bool]] = {
    "last_success_slot": _is_slot,
    "last_attempt_slot": _is_slot,
    "last_success_at": _is_timestamp,
    "last_attempt_at": _is_timestamp,
    "retry_at": _is_timestamp,
    "last_result": lambda v: v in (RESULT_OK, RESULT_FAILED),
    "last_error": lambda v: isinstance(v, str),
    "consecutive_failures": _is_count,
}


def _fmt(ts: float | None, tz) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts, tz).isoformat(timespec="minutes")
