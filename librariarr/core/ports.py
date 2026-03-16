from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class ArrCatalogPort(Protocol):
    def list_items(self) -> list[dict[str, Any]]: ...

    def update_item_path(self, item: dict[str, Any], path: str) -> bool: ...

    def refresh_item(self, item_id: int, *, force: bool = False) -> bool: ...


class LinkPort(Protocol):
    def ensure_link(
        self,
        folder: Path,
        shadow_root: Path,
        existing_links: set[Path],
        item: dict[str, Any] | None,
    ) -> tuple[Path, bool]: ...

    def list_links(self, shadow_roots: list[Path]) -> dict[Path, set[Path]]: ...

    def remove_link(self, link_path: Path) -> bool: ...


class FSScannerPort(Protocol):
    def discover_movie_folders(
        self,
        nested_root: Path,
        video_extensions: set[str],
        exclude_paths: list[str],
    ) -> dict[Path, Path]: ...

    def discover_series_folders(
        self,
        nested_root: Path,
        video_extensions: set[str],
        exclude_paths: list[str],
    ) -> dict[Path, Path]: ...

    def collect_current_links(self, shadow_roots: list[Path]) -> dict[Path, set[Path]]: ...


class TimerPort(Protocol):
    def now(self) -> float: ...
