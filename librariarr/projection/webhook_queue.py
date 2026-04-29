from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MovieWebhookEvent:
    movie_id: int
    event_type: str
    normalized_path: str
    enqueued_at: float


@dataclass(frozen=True)
class SeriesWebhookEvent:
    series_id: int
    event_type: str
    normalized_path: str
    enqueued_at: float


DEFAULT_DEDUPE_BUCKET_SECONDS = 120


class RadarrWebhookQueue:
    def __init__(
        self,
        max_items: int = 2000,
        dedupe_bucket_seconds: int = DEFAULT_DEDUPE_BUCKET_SECONDS,
    ) -> None:
        self.max_items = max(1, int(max_items))
        self.dedupe_bucket_seconds = max(1, int(dedupe_bucket_seconds))
        self._lock = threading.RLock()
        self._events_by_movie_id: OrderedDict[int, MovieWebhookEvent] = OrderedDict()
        self._dedupe_keys: dict[str, float] = {}
        self._dropped_events = 0

    def enqueue(
        self,
        *,
        movie_id: int,
        event_type: str,
        normalized_path: str,
    ) -> dict[str, int | bool]:
        now = time.time()
        bucket = int(now // self.dedupe_bucket_seconds)
        dedupe_key = f"{movie_id}:{event_type}:{normalized_path}:{bucket}"

        with self._lock:
            self._cleanup_old_dedupe_keys(now)
            if dedupe_key in self._dedupe_keys:
                return {
                    "queued": False,
                    "deduped": True,
                    "queue_size": len(self._events_by_movie_id),
                    "dropped_events": self._dropped_events,
                }

            self._dedupe_keys[dedupe_key] = now
            event = MovieWebhookEvent(
                movie_id=movie_id,
                event_type=event_type,
                normalized_path=normalized_path,
                enqueued_at=now,
            )
            if movie_id in self._events_by_movie_id:
                self._events_by_movie_id.pop(movie_id, None)
            self._events_by_movie_id[movie_id] = event

            dropped_now = 0
            while len(self._events_by_movie_id) > self.max_items:
                self._events_by_movie_id.popitem(last=False)
                self._dropped_events += 1
                dropped_now += 1
            if dropped_now:
                LOG.warning(
                    "Radarr webhook queue overflow: dropped %d event(s), "
                    "%d total dropped — next full maintenance reconcile will catch up",
                    dropped_now,
                    self._dropped_events,
                )

            return {
                "queued": True,
                "deduped": False,
                "queue_size": len(self._events_by_movie_id),
                "dropped_events": self._dropped_events,
            }

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._events_by_movie_id)

    def consume_movie_ids(self) -> set[int]:
        with self._lock:
            movie_ids = set(self._events_by_movie_id.keys())
            self._events_by_movie_id.clear()
            # After draining the queue, allow the same event keys to be queued again.
            # Keeping dedupe keys across consumes can incorrectly suppress legitimate
            # follow-up webhook events in tight reconcile loops and tests.
            self._dedupe_keys.clear()
            return movie_ids

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "queue_size": len(self._events_by_movie_id),
                "dropped_events": self._dropped_events,
            }

    def _cleanup_old_dedupe_keys(self, now: float) -> None:
        oldest_keep = now - (self.dedupe_bucket_seconds * 3)
        stale_keys = [key for key, ts in self._dedupe_keys.items() if ts < oldest_keep]
        for key in stale_keys:
            self._dedupe_keys.pop(key, None)


_WEBHOOK_QUEUE = RadarrWebhookQueue()


def get_radarr_webhook_queue() -> RadarrWebhookQueue:
    return _WEBHOOK_QUEUE


class SonarrWebhookQueue:
    def __init__(
        self,
        max_items: int = 2000,
        dedupe_bucket_seconds: int = DEFAULT_DEDUPE_BUCKET_SECONDS,
    ) -> None:
        self.max_items = max(1, int(max_items))
        self.dedupe_bucket_seconds = max(1, int(dedupe_bucket_seconds))
        self._lock = threading.RLock()
        self._events_by_series_id: OrderedDict[int, SeriesWebhookEvent] = OrderedDict()
        self._dedupe_keys: dict[str, float] = {}
        self._dropped_events = 0

    def enqueue(
        self,
        *,
        series_id: int,
        event_type: str,
        normalized_path: str,
    ) -> dict[str, int | bool]:
        now = time.time()
        bucket = int(now // self.dedupe_bucket_seconds)
        dedupe_key = f"{series_id}:{event_type}:{normalized_path}:{bucket}"

        with self._lock:
            self._cleanup_old_dedupe_keys(now)
            if dedupe_key in self._dedupe_keys:
                return {
                    "queued": False,
                    "deduped": True,
                    "queue_size": len(self._events_by_series_id),
                    "dropped_events": self._dropped_events,
                }

            self._dedupe_keys[dedupe_key] = now
            event = SeriesWebhookEvent(
                series_id=series_id,
                event_type=event_type,
                normalized_path=normalized_path,
                enqueued_at=now,
            )
            if series_id in self._events_by_series_id:
                self._events_by_series_id.pop(series_id, None)
            self._events_by_series_id[series_id] = event

            dropped_now = 0
            while len(self._events_by_series_id) > self.max_items:
                self._events_by_series_id.popitem(last=False)
                self._dropped_events += 1
                dropped_now += 1
            if dropped_now:
                LOG.warning(
                    "Sonarr webhook queue overflow: dropped %d event(s), "
                    "%d total dropped — next full maintenance reconcile will catch up",
                    dropped_now,
                    self._dropped_events,
                )

            return {
                "queued": True,
                "deduped": False,
                "queue_size": len(self._events_by_series_id),
                "dropped_events": self._dropped_events,
            }

    def has_pending(self) -> bool:
        with self._lock:
            return bool(self._events_by_series_id)

    def consume_series_ids(self) -> set[int]:
        with self._lock:
            series_ids = set(self._events_by_series_id.keys())
            self._events_by_series_id.clear()
            # Mirror Radarr queue behavior: once consumed, accept the same event
            # keys again for subsequent reconcile cycles.
            self._dedupe_keys.clear()
            return series_ids

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "queue_size": len(self._events_by_series_id),
                "dropped_events": self._dropped_events,
            }

    def _cleanup_old_dedupe_keys(self, now: float) -> None:
        oldest_keep = now - (self.dedupe_bucket_seconds * 3)
        stale_keys = [key for key, ts in self._dedupe_keys.items() if ts < oldest_keep]
        for key in stale_keys:
            self._dedupe_keys.pop(key, None)


_SONARR_WEBHOOK_QUEUE = SonarrWebhookQueue()


def get_sonarr_webhook_queue() -> SonarrWebhookQueue:
    return _SONARR_WEBHOOK_QUEUE
