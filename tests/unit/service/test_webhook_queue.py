from librariarr.projection.webhook_queue import RadarrWebhookQueue, SonarrWebhookQueue


def test_radarr_queue_allows_same_event_after_consume() -> None:
    queue = RadarrWebhookQueue(dedupe_bucket_seconds=120)

    first = queue.enqueue(movie_id=2, event_type="Test", normalized_path="/tmp/movie")
    assert first["queued"] is True
    assert queue.consume_movie_ids() == {2}

    second = queue.enqueue(movie_id=2, event_type="Test", normalized_path="/tmp/movie")
    assert second["queued"] is True
    assert second["deduped"] is False
    assert queue.consume_movie_ids() == {2}


def test_sonarr_queue_allows_same_event_after_consume() -> None:
    queue = SonarrWebhookQueue(dedupe_bucket_seconds=120)

    first = queue.enqueue(series_id=7, event_type="Test", normalized_path="/tmp/series")
    assert first["queued"] is True
    assert queue.consume_series_ids() == {7}

    second = queue.enqueue(series_id=7, event_type="Test", normalized_path="/tmp/series")
    assert second["queued"] is True
    assert second["deduped"] is False
    assert queue.consume_series_ids() == {7}
