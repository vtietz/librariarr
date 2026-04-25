import logging

import librariarr.web.log_buffer as log_buffer_module


class _FakeLogger:
    def __init__(self, *, propagate: bool) -> None:
        self.propagate = propagate
        self.handlers: list[logging.Handler] = []

    def addHandler(self, handler: logging.Handler) -> None:  # noqa: N802
        self.handlers.append(handler)


def test_install_log_buffer_attaches_root_and_non_propagating_uvicorn_loggers(monkeypatch) -> None:
    root = _FakeLogger(propagate=True)
    uvicorn = _FakeLogger(propagate=False)
    uvicorn_error = _FakeLogger(propagate=False)
    uvicorn_access = _FakeLogger(propagate=False)
    other = _FakeLogger(propagate=True)

    fake_loggers: dict[str, _FakeLogger] = {
        "": root,
        "uvicorn": uvicorn,
        "uvicorn.error": uvicorn_error,
        "uvicorn.access": uvicorn_access,
        "other": other,
    }

    def fake_get_logger(name: str | None = None):
        key = "" if name is None else name
        return fake_loggers[key]

    monkeypatch.setattr(log_buffer_module, "_get_logger", fake_get_logger)
    monkeypatch.setattr(log_buffer_module, "_global_buffer", None)

    buf = log_buffer_module.install_log_buffer(maxlen=10)

    assert root.handlers == [buf]
    assert uvicorn.handlers == [buf]
    assert uvicorn_error.handlers == [buf]
    assert uvicorn_access.handlers == [buf]
    assert other.handlers == []


def test_install_log_buffer_is_idempotent_and_does_not_duplicate_handlers(monkeypatch) -> None:
    root = _FakeLogger(propagate=True)
    uvicorn = _FakeLogger(propagate=False)
    uvicorn_error = _FakeLogger(propagate=False)
    uvicorn_access = _FakeLogger(propagate=False)

    fake_loggers: dict[str, _FakeLogger] = {
        "": root,
        "uvicorn": uvicorn,
        "uvicorn.error": uvicorn_error,
        "uvicorn.access": uvicorn_access,
    }

    def fake_get_logger(name: str | None = None):
        key = "" if name is None else name
        return fake_loggers[key]

    monkeypatch.setattr(log_buffer_module, "_get_logger", fake_get_logger)
    monkeypatch.setattr(log_buffer_module, "_global_buffer", None)

    first = log_buffer_module.install_log_buffer(maxlen=10)
    second = log_buffer_module.install_log_buffer(maxlen=10)

    assert first is second
    assert root.handlers.count(first) == 1
    assert uvicorn.handlers.count(first) == 1
    assert uvicorn_error.handlers.count(first) == 1
    assert uvicorn_access.handlers.count(first) == 1
