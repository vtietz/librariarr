from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any


def _default_state() -> dict[str, Any]:
    return {
        "jobs": {"items": {}, "order": []},
        "dashboard": None,
        "cache_snapshots": {},
    }


class PersistentStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def load_state(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return _default_state()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return _default_state()
            return self._normalize_state(payload)

    def load_jobs(self) -> tuple[dict[str, dict[str, Any]], list[str]]:
        state = self.load_state()
        jobs = state.get("jobs")
        if not isinstance(jobs, dict):
            return {}, []
        items = jobs.get("items")
        order = jobs.get("order")
        if not isinstance(items, dict) or not isinstance(order, list):
            return {}, []
        normalized_items = {
            str(job_id): dict(record)
            for job_id, record in items.items()
            if isinstance(record, dict)
        }
        normalized_order = [str(job_id) for job_id in order if str(job_id) in normalized_items]
        return normalized_items, normalized_order

    def save_jobs(self, items: dict[str, dict[str, Any]], order: list[str]) -> None:
        with self._lock:
            state = self.load_state()
            state["jobs"] = {
                "items": {job_id: dict(record) for job_id, record in items.items()},
                "order": list(order),
                "updated_at": time.time(),
            }
            self._write_state_locked(state)

    def load_dashboard(self) -> dict[str, Any] | None:
        state = self.load_state()
        payload = state.get("dashboard")
        return dict(payload) if isinstance(payload, dict) else None

    def save_dashboard(self, payload: dict[str, Any]) -> None:
        with self._lock:
            state = self.load_state()
            state["dashboard"] = dict(payload)
            self._write_state_locked(state)

    def load_cache_snapshot(self, cache_name: str) -> dict[str, Any] | None:
        state = self.load_state()
        snapshots = state.get("cache_snapshots")
        if not isinstance(snapshots, dict):
            return None
        payload = snapshots.get(cache_name)
        return dict(payload) if isinstance(payload, dict) else None

    def save_cache_snapshot(self, cache_name: str, payload: dict[str, Any]) -> None:
        with self._lock:
            state = self.load_state()
            snapshots = state.get("cache_snapshots")
            if not isinstance(snapshots, dict):
                snapshots = {}
            snapshots[cache_name] = dict(payload)
            state["cache_snapshots"] = snapshots
            self._write_state_locked(state)

    def _write_state_locked(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def _normalize_state(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return _default_state()

        payload.setdefault("jobs", {"items": {}, "order": []})
        payload.setdefault("dashboard", None)
        payload.setdefault("cache_snapshots", {})

        jobs = payload.get("jobs")
        if not isinstance(jobs, dict):
            jobs = {"items": {}, "order": []}
            payload["jobs"] = jobs
        items = jobs.get("items")
        order = jobs.get("order")
        if not isinstance(items, dict):
            jobs["items"] = {}
        if not isinstance(order, list):
            jobs["order"] = []

        if not isinstance(payload.get("cache_snapshots"), dict):
            payload["cache_snapshots"] = {}

        return payload
