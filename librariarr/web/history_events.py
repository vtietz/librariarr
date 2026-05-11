from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from .state_store import PersistentStateStore

MAX_HISTORY_ITEMS = 2000

_HISTORY_HANDLER: logging.Handler | None = None
_HISTORY_LOCK = threading.Lock()
_EVENT_COUNTER = 0

_MOVIE_IMPORT_RE = re.compile(
    r"Ingest moved movie folder from library root to managed root:.*destination=(.+)$"
)
_SERIES_IMPORT_RE = re.compile(
    r"Ingest moved series folder from shadow root to managed root:.*destination=(.+)$"
)
_MOVIE_FILE_REPLACE_RE = re.compile(
    r"File-level fs operations for movie_id=\d+: moved=(\d+) failed=(\d+)"
)
_SERIES_FILE_REPLACE_RE = re.compile(
    r"File-level fs operations for series_id=\d+: moved=(\d+) failed=(\d+)"
)
_RADARR_AUTO_ADD_RE = re.compile(r"Radarr auto-add processed: added=(\d+) total_unmatched=(\d+)")
_SONARR_AUTO_ADD_RE = re.compile(r"Sonarr auto-add processed: added=(\d+) total_unmatched=(\d+)")
_MOVIE_PROJECTION_RE = re.compile(
    r"Movie projection reconcile:.*projected_files=(\d+) unchanged_files=(\d+) skipped_files=(\d+)"
)
_SERIES_PROJECTION_RE = re.compile(
    r"Sonarr projection reconcile:.*projected_files=(\d+) unchanged_files=(\d+) skipped_files=(\d+)"
)
_STALE_CLEANUP_RE = re.compile(r"Stale shadow cleanup removed (\d+) orphaned managed file\(s\)")


class HistoryEventHandler(logging.Handler):
    def __init__(self, state_store: PersistentStateStore) -> None:
        super().__init__()
        self._state_store = state_store

    def set_state_store(self, state_store: PersistentStateStore) -> None:
        self._state_store = state_store

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.INFO:
            return

        try:
            message = record.getMessage()
        except Exception:
            return

        entry = _entry_from_log_message(message)
        if entry is None:
            return

        append_history_event(self._state_store, **entry)


def install_history_event_handler(state_store: PersistentStateStore) -> logging.Handler:
    global _HISTORY_HANDLER
    with _HISTORY_LOCK:
        if _HISTORY_HANDLER is None:
            _HISTORY_HANDLER = HistoryEventHandler(state_store)
        elif isinstance(_HISTORY_HANDLER, HistoryEventHandler):
            _HISTORY_HANDLER.set_state_store(state_store)
        root_logger = logging.getLogger()
        if not any(existing is _HISTORY_HANDLER for existing in root_logger.handlers):
            root_logger.addHandler(_HISTORY_HANDLER)
        return _HISTORY_HANDLER


def _next_event_id() -> str:
    global _EVENT_COUNTER
    with _HISTORY_LOCK:
        _EVENT_COUNTER += 1
        return f"{int(time.time() * 1000)}-{_EVENT_COUNTER}"


def _path_label(path_raw: str) -> str:
    path = Path(path_raw.strip())
    if not path.name:
        return "item"
    return path.name


def _movie_import_event(message: str) -> dict[str, str] | None:
    movie_import_match = _MOVIE_IMPORT_RE.search(message)
    if movie_import_match is None:
        return None
    folder_name = _path_label(movie_import_match.group(1))
    return {
        "scenario": "1",
        "category": "ingest",
        "title": f"Imported movie: {folder_name}",
        "message": "New movie content was moved into the managed library structure.",
    }


def _series_import_event(message: str) -> dict[str, str] | None:
    series_import_match = _SERIES_IMPORT_RE.search(message)
    if series_import_match is None:
        return None
    folder_name = _path_label(series_import_match.group(1))
    return {
        "scenario": "1",
        "category": "ingest",
        "title": f"Imported series: {folder_name}",
        "message": "New series content was moved into the managed library structure.",
    }


def _replace_event(message: str) -> dict[str, str] | None:
    movie_replace_match = _MOVIE_FILE_REPLACE_RE.search(message)
    if movie_replace_match is not None:
        moved = int(movie_replace_match.group(1))
        failed = int(movie_replace_match.group(2))
        if moved <= 0:
            return None
        return {
            "scenario": "2",
            "category": "replacement",
            "title": f"Movie files updated ({moved})",
            "message": (
                f"Replaced {moved} movie file(s) with newer versions"
                + (f" ({failed} failed)." if failed > 0 else ".")
            ),
        }

    series_replace_match = _SERIES_FILE_REPLACE_RE.search(message)
    if series_replace_match is None:
        return None
    moved = int(series_replace_match.group(1))
    failed = int(series_replace_match.group(2))
    if moved <= 0:
        return None
    return {
        "scenario": "2",
        "category": "replacement",
        "title": f"Episode files updated ({moved})",
        "message": (
            f"Replaced {moved} episode file(s) with newer versions"
            + (f" ({failed} failed)." if failed > 0 else ".")
        ),
    }


def _auto_add_event(message: str) -> dict[str, str] | None:
    radarr_auto_add_match = _RADARR_AUTO_ADD_RE.search(message)
    if radarr_auto_add_match is not None:
        added = int(radarr_auto_add_match.group(1))
        total = int(radarr_auto_add_match.group(2))
        if added <= 0:
            return None
        return {
            "scenario": "4",
            "category": "auto_add",
            "title": f"Movies auto-added to Radarr ({added})",
            "message": (
                f"Added {added} unmatched movie folder(s) to Radarr out of {total} detected."
            ),
        }

    sonarr_auto_add_match = _SONARR_AUTO_ADD_RE.search(message)
    if sonarr_auto_add_match is None:
        return None
    added = int(sonarr_auto_add_match.group(1))
    total = int(sonarr_auto_add_match.group(2))
    if added <= 0:
        return None
    return {
        "scenario": "4",
        "category": "auto_add",
        "title": f"Series auto-added to Sonarr ({added})",
        "message": (f"Added {added} unmatched series folder(s) to Sonarr out of {total} detected."),
    }


def _projection_event(message: str) -> dict[str, str] | None:
    movie_projection_match = _MOVIE_PROJECTION_RE.search(message)
    if movie_projection_match is not None:
        projected = int(movie_projection_match.group(1))
        unchanged = int(movie_projection_match.group(2))
        if projected <= 0:
            return None
        return {
            "scenario": "3",
            "category": "projection",
            "title": f"Movie library links refreshed ({projected})",
            "message": f"Updated {projected} movie link(s); {unchanged} already up to date.",
        }

    series_projection_match = _SERIES_PROJECTION_RE.search(message)
    if series_projection_match is None:
        return None
    projected = int(series_projection_match.group(1))
    unchanged = int(series_projection_match.group(2))
    if projected <= 0:
        return None
    return {
        "scenario": "3",
        "category": "projection",
        "title": f"Series library links refreshed ({projected})",
        "message": f"Updated {projected} series link(s); {unchanged} already up to date.",
    }


def _cleanup_event(message: str) -> dict[str, str] | None:
    stale_cleanup_match = _STALE_CLEANUP_RE.search(message)
    if stale_cleanup_match is None:
        return None
    removed = int(stale_cleanup_match.group(1))
    if removed <= 0:
        return None
    return {
        "scenario": "8",
        "category": "cleanup",
        "title": f"Removed stale links ({removed})",
        "message": "Removed links that no longer pointed to a valid managed file.",
    }


def _entry_from_log_message(message: str) -> dict[str, str] | None:
    parsers = (
        _movie_import_event,
        _series_import_event,
        _replace_event,
        _auto_add_event,
        _projection_event,
        _cleanup_event,
    )
    for parser in parsers:
        entry = parser(message)
        if entry is not None:
            return entry
    return None


def clear_history_events(state_store: PersistentStateStore) -> int:
    items = state_store.load_history()
    removed = len(items)
    state_store.save_history([])
    return removed


def append_history_event(
    state_store: PersistentStateStore,
    *,
    scenario: str,
    category: str,
    title: str,
    message: str,
) -> dict[str, Any]:
    items = state_store.load_history()
    entry: dict[str, Any] = {
        "id": _next_event_id(),
        "timestamp": time.time(),
        "scenario": scenario,
        "category": category,
        "title": title,
        "message": message,
    }
    items.insert(0, entry)
    if len(items) > MAX_HISTORY_ITEMS:
        items = items[:MAX_HISTORY_ITEMS]
    state_store.save_history(items)
    return entry
