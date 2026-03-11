from librariarr.radarr import RadarrClient


def test_try_update_moviefile_quality_skips_when_already_set(monkeypatch) -> None:
    client = RadarrClient(base_url="http://radarr:7878", api_key="test")
    calls: list[tuple[str, str, dict]] = []

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)

    movie = {
        "id": 1,
        "title": "Fixture",
        "movieFile": {
            "id": 11,
            "quality": {
                "quality": {"id": 9, "name": "HDTV-1080p"},
            },
        },
    }

    changed = client.try_update_moviefile_quality(movie, quality_id=9)

    assert changed is False
    assert calls == []


def test_try_update_moviefile_quality_updates_when_different(monkeypatch) -> None:
    client = RadarrClient(base_url="http://radarr:7878", api_key="test")
    calls: list[tuple[str, str, dict]] = []

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)

    movie = {
        "id": 1,
        "title": "Fixture",
        "movieFile": {
            "id": 11,
            "quality": {
                "quality": {"id": 7, "name": "Bluray-1080p"},
            },
        },
    }

    changed = client.try_update_moviefile_quality(movie, quality_id=9)

    assert changed is True
    assert len(calls) == 1
    method, path, kwargs = calls[0]
    assert method == "PUT"
    assert path == "/moviefile/editor"
    assert kwargs["json"]["movieFileIds"] == [11]
    assert kwargs["json"]["quality"]["quality"]["id"] == 9


def test_parse_title_calls_parse_endpoint(monkeypatch) -> None:
    client = RadarrClient(base_url="http://radarr:7878", api_key="test")
    calls: list[tuple[str, str, dict]] = []

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return {"title": "Fixture", "customFormats": [{"id": 42, "name": "German"}]}

    monkeypatch.setattr(client, "_request", _fake_request)

    parsed = client.parse_title("Fixture.Title.2017.1080p.x265")

    assert parsed["title"] == "Fixture"
    assert len(calls) == 1
    method, path, kwargs = calls[0]
    assert method == "GET"
    assert path == "/parse"
    assert kwargs["params"]["title"] == "Fixture.Title.2017.1080p.x265"


def test_refresh_movie_debounce_skips_within_window(monkeypatch) -> None:
    client = RadarrClient(
        base_url="http://radarr:7878",
        api_key="test",
        refresh_debounce_seconds=15,
    )
    calls: list[tuple[str, str, dict]] = []
    current_time = {"value": 1000.0}

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    monkeypatch.setattr("librariarr.radarr.time.time", lambda: current_time["value"])

    assert client.refresh_movie(42) is True
    current_time["value"] += 5.0
    assert client.refresh_movie(42) is False
    current_time["value"] += 11.0
    assert client.refresh_movie(42) is True

    assert len(calls) == 2
    assert calls[0][0] == "POST"
    assert calls[0][1] == "/command"


def test_refresh_movie_force_bypasses_debounce(monkeypatch) -> None:
    client = RadarrClient(
        base_url="http://radarr:7878",
        api_key="test",
        refresh_debounce_seconds=60,
    )
    calls: list[tuple[str, str, dict]] = []
    current_time = {"value": 2000.0}

    def _fake_request(method: str, path: str, **kwargs):
        calls.append((method, path, kwargs))
        return None

    monkeypatch.setattr(client, "_request", _fake_request)
    monkeypatch.setattr("librariarr.radarr.time.time", lambda: current_time["value"])

    assert client.refresh_movie(7) is True
    current_time["value"] += 1.0
    assert client.refresh_movie(7, force=True) is True

    assert len(calls) == 2
