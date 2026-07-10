import json

import requests

from librariarr.clients.errors import describe_http_error


class _FakeResponse:
    def __init__(self, *, json_body=None, text=""):
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


def test_describe_http_error_extracts_radarr_validation_array():
    body = [
        {
            "propertyName": "TmdbId",
            "errorMessage": "This movie has already been added",
            "errorCode": "MovieExistsValidator",
            "severity": "error",
        }
    ]
    response = _FakeResponse(json_body=body, text=json.dumps(body))
    exc = requests.HTTPError("400 Client Error: Bad Request for url: ...", response=response)

    detail = describe_http_error(exc)

    assert "already been added" in detail
    assert detail.startswith("400 Client Error")


def test_describe_http_error_extracts_dict_message():
    response = _FakeResponse(json_body={"message": "Invalid quality profile"})
    exc = requests.HTTPError("400 Client Error", response=response)

    assert "Invalid quality profile" in describe_http_error(exc)


def test_describe_http_error_falls_back_to_raw_text():
    response = _FakeResponse(json_body=None, text="  Root folder does not exist  ")
    exc = requests.HTTPError("400 Client Error", response=response)

    assert "Root folder does not exist" in describe_http_error(exc)


def test_describe_http_error_no_response_returns_plain_str():
    exc = requests.ConnectionError("connection refused")
    assert describe_http_error(exc) == "connection refused"


def test_describe_http_error_empty_body_returns_plain_str():
    response = _FakeResponse(json_body=None, text="")
    exc = requests.HTTPError("400 Client Error", response=response)
    assert describe_http_error(exc) == "400 Client Error"
