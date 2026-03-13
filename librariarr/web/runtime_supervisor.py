from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_config
from ..service import LibrariArrService

LOG = logging.getLogger(__name__)


@dataclass
class RuntimeSupervisor:
    config_path: Path
    poll_interval_seconds: float = 2.0
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False)
    _watch_stop: threading.Event = field(default_factory=threading.Event, init=False)
    _watch_thread: threading.Thread | None = field(default=None, init=False)
    _runtime_thread: threading.Thread | None = field(default=None, init=False)
    _runtime_stop: threading.Event | None = field(default=None, init=False)
    _last_config_mtime_ns: int | None = field(default=None, init=False)

    def start(self) -> bool:
        with self._lock:
            started = self._start_runtime_locked("startup")
            self._last_config_mtime_ns = self._read_config_mtime_ns()
            self._watch_stop.clear()
            self._watch_thread = threading.Thread(
                target=self._watch_config_loop,
                daemon=True,
                name="librariarr-config-watch",
            )
            self._watch_thread.start()
            return started

    def stop(self) -> None:
        with self._lock:
            self._watch_stop.set()
            watch_thread = self._watch_thread
            self._watch_thread = None
            self._stop_runtime_locked()

        if watch_thread is not None and watch_thread.is_alive():
            watch_thread.join(timeout=5)

    def restart_for_config_change(self, reason: str) -> bool:
        with self._lock:
            restarted = self._restart_runtime_locked(reason)
            self._last_config_mtime_ns = self._read_config_mtime_ns()
            return restarted

    def _watch_config_loop(self) -> None:
        while not self._watch_stop.wait(self.poll_interval_seconds):
            with self._lock:
                current_mtime = self._read_config_mtime_ns()
                if current_mtime is None:
                    continue
                if self._last_config_mtime_ns is None:
                    self._last_config_mtime_ns = current_mtime
                    continue
                if current_mtime == self._last_config_mtime_ns:
                    continue
                self._last_config_mtime_ns = current_mtime
                self._restart_runtime_locked("detected config file change")

    def _read_config_mtime_ns(self) -> int | None:
        try:
            return self.config_path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _build_runtime(self) -> tuple[threading.Event, threading.Thread]:
        runtime_config = load_config(self.config_path)
        service = LibrariArrService(runtime_config)
        runtime_stop = threading.Event()
        runtime_thread = threading.Thread(
            target=service.run,
            kwargs={"stop_event": runtime_stop},
            daemon=True,
            name="librariarr-sync",
        )
        return runtime_stop, runtime_thread

    def _start_runtime_locked(self, reason: str) -> bool:
        try:
            runtime_stop, runtime_thread = self._build_runtime()
        except Exception:
            LOG.exception("Failed to start background reconcile loop (%s)", reason)
            return False

        self._runtime_stop = runtime_stop
        self._runtime_thread = runtime_thread
        runtime_thread.start()
        LOG.info("Started background reconcile loop (%s)", reason)
        return True

    def _restart_runtime_locked(self, reason: str) -> bool:
        try:
            runtime_stop, runtime_thread = self._build_runtime()
        except Exception:
            LOG.exception("Ignoring config change; keeping existing runtime (%s)", reason)
            return False

        self._stop_runtime_locked()
        self._runtime_stop = runtime_stop
        self._runtime_thread = runtime_thread
        runtime_thread.start()
        LOG.info("Restarted background reconcile loop (%s)", reason)
        return True

    def _stop_runtime_locked(self) -> None:
        runtime_stop = self._runtime_stop
        runtime_thread = self._runtime_thread
        self._runtime_stop = None
        self._runtime_thread = None

        if runtime_stop is not None:
            runtime_stop.set()
        if runtime_thread is not None and runtime_thread.is_alive():
            runtime_thread.join(timeout=30)
            if runtime_thread.is_alive():
                LOG.warning("Background reconcile loop did not stop within timeout")
