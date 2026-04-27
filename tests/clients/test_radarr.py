import pytest
import requests

from librariarr.clients.radarr import RadarrClient


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
    monkeypatch.setattr("librariarr.clients.radarr.time.time", lambda: current_time["value"])

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
    monkeypatch.setattr("librariarr.clients.radarr.time.time", lambda: current_time["value"])

    assert client.refresh_movie(7) is True
    current_time["value"] += 1.0
    assert client.refresh_movie(7, force=True) is True

    assert len(calls) == 2


def test_request_retries_timeout_for_get(monkeypatch) -> None:
    client = RadarrClient(
        base_url="http://radarr:7878",
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

    movies = client.get_movies()

    assert movies == []
    assert calls["count"] == 2


def test_request_does_not_retry_post_on_timeout(monkeypatch) -> None:
    client = RadarrClient(
        base_url="http://radarr:7878",
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
        client.refresh_movie(42)
    except requests.Timeout:
        pass
    else:
        raise AssertionError("Expected timeout to be raised for non-retried POST")

    assert calls["count"] == 1


def test_get_movies_by_ids_fetches_sorted_unique_ids(monkeypatch) -> None:
    client = RadarrClient(base_url="http://radarr:7878", api_key="test")
    calls: list[str] = []

    def _fake_request(method: str, path: str, **kwargs):
        del kwargs
        calls.append(path)
        assert method == "GET"
        movie_id = int(path.rsplit("/", maxsplit=1)[1])
        return {"id": movie_id, "title": f"Movie {movie_id}"}

    monkeypatch.setattr(client, "_request", _fake_request)

    movies = client.get_movies_by_ids([2, 1, 2])

    assert [movie["id"] for movie in movies] == [1, 2]
    assert calls == ["/movie/1", "/movie/2"]


def test_get_movies_by_ids_skips_404(monkeypatch) -> None:
    client = RadarrClient(base_url="http://radarr:7878", api_key="test")

    class _Response:
        status_code = 404

    def _fake_request(method: str, path: str, **kwargs):
        del kwargs
        assert method == "GET"
        movie_id = int(path.rsplit("/", maxsplit=1)[1])
        if movie_id == 2:
            raise requests.HTTPError("not found", response=_Response())
        return {"id": movie_id}

    monkeypatch.setattr(client, "_request", _fake_request)

    movies = client.get_movies_by_ids([1, 2])

    assert [movie["id"] for movie in movies] == [1]


def test_get_movies_by_ids_reraises_non_404(monkeypatch) -> None:
    client = RadarrClient(base_url="http://radarr:7878", api_key="test")

    class _Response:
        status_code = 500

    def _fake_request(method: str, path: str, **kwargs):
        del method, path, kwargs
        raise requests.HTTPError("boom", response=_Response())

    monkeypatch.setattr(client, "_request", _fake_request)

    with pytest.raises(requests.HTTPError):
        client.get_movies_by_ids([1])
