from librariarr.sonarr import SonarrClient


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
    monkeypatch.setattr("librariarr.sonarr.time.time", lambda: current_time["value"])

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
    monkeypatch.setattr("librariarr.sonarr.time.time", lambda: current_time["value"])

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
