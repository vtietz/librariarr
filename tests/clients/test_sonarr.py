import requests

from librariarr.clients.sonarr import SonarrClient


def test_refresh_series_debounce_skips_within_window(monkeypatch) -> None:
    client = SonarrClient(
        base_url="http://sonarr:8989",
        api_key="test",
        refresh_debounce_seconds=15,
    )
    calls: list[tuple[str, str, dict]] = []
    current_time = {"value": 1000.0}

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    monkeypatch.setattr("librariarr.clients.sonarr.time.time", lambda: current_time["value"])

    assert client.refresh_series(42) is True
    current_time["value"] += 5.0
    assert client.refresh_series(42) is False
    current_time["value"] += 11.0
    assert client.refresh_series(42) is True

    assert len(calls) == 2
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/command"


def test_refresh_series_force_bypasses_debounce(monkeypatch) -> None:
    client = SonarrClient(
        base_url="http://sonarr:8989",
        api_key="test",
        refresh_debounce_seconds=60,
    )
    calls: list[tuple[str, str, dict]] = []
    current_time = {"value": 2000.0}

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    monkeypatch.setattr("librariarr.clients.sonarr.time.time", lambda: current_time["value"])

    assert client.refresh_series(7) is True
    current_time["value"] += 1.0
    assert client.refresh_series(7, force=True) is True

    assert len(calls) == 2


def test_update_series_path_skips_when_unchanged(monkeypatch) -> None:
    client = SonarrClient(base_url="http://sonarr:8989", api_key="test")
    calls: list[tuple[str, str, dict]] = []

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)

    series = {"id": 1, "title": "Fixture", "path": "/data/library/Fixture"}
    changed = client.update_series_path(series, "/data/library/Fixture")

    assert changed is False
    assert calls == []


def test_request_retries_timeout_for_get(monkeypatch) -> None:
    client = SonarrClient(
        base_url="http://sonarr:8989",
        api_key="test",
        retry_attempts=1,
        retry_backoff_seconds=0,
    )
    calls = {"count": 0}

    class _Response:
        content = b"[]"

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return []

    def _fake_session_request(method: str, url: str, timeout: int, **kwargs):
        del url, timeout, kwargs
        calls["count"] += 1
        if calls["count"] == 1:
            raise requests.Timeout("timed out")
        assert method == "GET"
        return _Response()

    monkeypatch.setattr(client.session, "request", _fake_session_request)

    series = client.get_series()

    assert series == []
    assert calls["count"] == 2


def test_request_does_not_retry_post_on_timeout(monkeypatch) -> None:
    client = SonarrClient(
        base_url="http://sonarr:8989",
        api_key="test",
        retry_attempts=2,
        retry_backoff_seconds=0,
    )
    calls = {"count": 0}

    def _fake_session_request(method: str, url: str, timeout: int, **kwargs):
        del url, timeout, kwargs
        calls["count"] += 1
        assert method == "POST"
        raise requests.Timeout("timed out")

    monkeypatch.setattr(client.session, "request", _fake_session_request)

    try:
        client.refresh_series(42)
    except requests.Timeout:
        pass
    else:
        raise AssertionError("Expected timeout to be raised for non-retried POST")

    assert calls["count"] == 1
