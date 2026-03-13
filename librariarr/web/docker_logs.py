from __future__ import annotations

import asyncio
import re
import subprocess
from collections.abc import AsyncIterator

from fastapi import HTTPException

_CONTAINER_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")
_LOG_LEVEL_RE = re.compile(
    r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|TRACE|FATAL)\b", re.IGNORECASE
)


def _normalize_log_level(level: str) -> str:
    normalized = level.upper()
    if normalized == "WARN":
        return "WARNING"
    if normalized == "FATAL":
        return "CRITICAL"
    return normalized


def _detect_log_level(line: str) -> str:
    match = _LOG_LEVEL_RE.search(line)
    if not match:
        return "UNKNOWN"
    return _normalize_log_level(match.group(1))


def _validate_container_name(container: str) -> None:
    if not _CONTAINER_NAME_RE.match(container):
        raise HTTPException(status_code=400, detail="Invalid container name.")


def read_docker_logs(container: str, tail: int) -> list[dict[str, str]]:
    _validate_container_name(container)

    command = ["docker", "logs", "--tail", str(tail), container]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Docker CLI is not available.") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Timed out while reading Docker logs.") from exc

    if result.returncode != 0:
        detail = result.stderr.strip() or "Unable to read Docker logs."
        raise HTTPException(status_code=502, detail=detail)

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return [{"line": line, "level": _detect_log_level(line)} for line in reversed(lines)]


async def stream_docker_logs(container: str, tail: int) -> AsyncIterator[dict[str, str]]:
    _validate_container_name(container)

    command = ["docker", "logs", "--follow", "--tail", str(tail), container]
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Docker CLI is not available.") from exc

    try:
        while True:
            if process.stdout is None:
                break

            raw_line = await process.stdout.readline()
            if not raw_line:
                break

            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            yield {"line": line, "level": _detect_log_level(line)}

        return_code = await process.wait()
        if return_code != 0:
            detail = "Unable to stream Docker logs."
            if process.stderr is not None:
                stderr_output = await process.stderr.read()
                stderr_text = stderr_output.decode("utf-8", errors="replace").strip()
                if stderr_text:
                    detail = stderr_text
            raise HTTPException(status_code=502, detail=detail)
    finally:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except TimeoutError:
                process.kill()
                await process.wait()
