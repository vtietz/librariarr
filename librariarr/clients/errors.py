"""Shared helper to surface Radarr/Sonarr's actual validation error text.

``requests``' default ``HTTPError`` message is just "400 Client Error: Bad
Request for url: ..." — the actionable reason (e.g. "This movie has already
been added") lives in the response body, which is otherwise discarded.
"""

from __future__ import annotations

import requests


def describe_http_error(exc: requests.RequestException) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)

    detail: str | None = None
    try:
        body = response.json()
    except ValueError:
        body = None

    if isinstance(body, list):
        messages = [
            str(item.get("errorMessage") or item.get("message") or item)
            for item in body
            if isinstance(item, dict)
        ]
        detail = "; ".join(m for m in messages if m) or None
    elif isinstance(body, dict):
        detail = str(body.get("errorMessage") or body.get("message") or "").strip() or None

    if not detail:
        text = (response.text or "").strip()
        detail = text[:300] if text else None

    return f"{exc} — {detail}" if detail else str(exc)
