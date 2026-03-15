from __future__ import annotations

import logging
import re
import threading
from collections import deque
from itertools import islice

_LOG_LEVEL_RE = re.compile(
    r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|TRACE|FATAL)\b", re.IGNORECASE
)

_LEVEL_NORMALIZE: dict[str, str] = {"WARN": "WARNING", "FATAL": "CRITICAL"}


def _detect_level(record: logging.LogRecord) -> str:
    return record.levelname or "UNKNOWN"


class LogRingBuffer(logging.Handler):
    """A logging handler that keeps the last *maxlen* formatted log records."""

    def __init__(self, maxlen: int = 2000) -> None:
        super().__init__()
        self._maxlen = maxlen
        self._buffer: deque[dict[str, str]] = deque(maxlen=maxlen)
        self._lock_obj = threading.Lock()
        self._sequence = 0
        self._waiters: list[threading.Event] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            line = record.getMessage()
        level = _detect_level(record)
        with self._lock_obj:
            self._sequence += 1
            self._buffer.append({"line": line, "level": level, "seq": str(self._sequence)})
            for waiter in self._waiters:
                waiter.set()

    def get_entries(self, tail: int = 250) -> list[dict[str, str]]:
        with self._lock_obj:
            if tail > 0:
                items = list(islice(reversed(self._buffer), tail))
            else:
                items = list(reversed(self._buffer))
        return items

    def get_entries_since(self, seq: int) -> list[dict[str, str]]:
        with self._lock_obj:
            return [entry for entry in self._buffer if int(entry["seq"]) > seq]

    @property
    def sequence(self) -> int:
        with self._lock_obj:
            return self._sequence

    def wait_for_new(self, timeout: float = 2.0) -> bool:
        event = threading.Event()
        with self._lock_obj:
            self._waiters.append(event)
        try:
            return event.wait(timeout=timeout)
        finally:
            with self._lock_obj:
                try:
                    self._waiters.remove(event)
                except ValueError:
                    pass


_global_buffer: LogRingBuffer | None = None


def install_log_buffer(maxlen: int = 2000) -> LogRingBuffer:
    global _global_buffer
    if _global_buffer is not None:
        return _global_buffer
    buf = LogRingBuffer(maxlen=maxlen)
    buf.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    logging.getLogger().addHandler(buf)
    _global_buffer = buf
    return buf


def get_log_buffer() -> LogRingBuffer | None:
    return _global_buffer
