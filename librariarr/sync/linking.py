from __future__ import annotations

import logging
import re
from pathlib import Path

from .naming import canonical_name_from_folder, safe_path_component

NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class ShadowLinkManager:
    def __init__(self, nested_roots: list[Path], logger: logging.Logger | None = None) -> None:
        self.nested_roots = nested_roots
        self.log = logger or logging.getLogger(__name__)

    def ensure_link(
        self,
        folder: Path,
        shadow_root: Path,
        existing_links: set[Path],
        movie: dict | None,
    ) -> tuple[Path, bool]:
        base_name = self._canonical_link_name(folder, movie)
        desired = shadow_root / base_name

        for link in existing_links:
            if link == desired and link.exists() and link.is_symlink():
                try:
                    if link.resolve(strict=False) == folder:
                        return link, False
                except OSError:
                    pass

        created = not (desired.exists() or desired.is_symlink())
        link = self._create_link(folder, shadow_root, base_name)
        return link, created

    def _safe_link_name(self, folder: Path) -> str:
        return safe_path_component(folder.name)

    def _canonical_link_name(self, folder: Path, movie: dict | None) -> str:
        if movie is None:
            return canonical_name_from_folder(self._safe_link_name(folder))

        title = safe_path_component(str(movie.get("title") or "").strip()) or self._safe_link_name(
            folder
        )
        year = movie.get("year")
        if isinstance(year, int):
            return f"{title} ({year})"
        return title

    def _normalize_name_part(self, value: str) -> str:
        cleaned = NON_ALNUM_RE.sub("-", value.strip())
        return cleaned.strip("-")

    def _collision_qualifier(self, folder: Path) -> str:
        for root in self.nested_roots:
            try:
                relative = folder.relative_to(root)
            except ValueError:
                continue

            parent_parts = [self._normalize_name_part(part) for part in relative.parts[:-1]]
            qualifier_parts = [self._normalize_name_part(root.name)] + parent_parts
            qualifier = "-".join(part for part in qualifier_parts if part)
            if qualifier:
                return qualifier
        return ""

    def _create_link(self, folder: Path, shadow_root: Path, base_name: str) -> Path:
        candidate = shadow_root / base_name
        qualifier = self._collision_qualifier(folder)
        qualified_candidate = shadow_root / f"{base_name}--{qualifier}" if qualifier else None
        counter = 2

        while candidate.exists() or candidate.is_symlink():
            try:
                if candidate.is_symlink() and candidate.resolve(strict=False) == folder:
                    return candidate
            except OSError:
                pass

            if qualified_candidate is not None:
                candidate = qualified_candidate
                qualified_candidate = None
                continue

            candidate = shadow_root / f"{base_name}--{counter}"
            counter += 1

        candidate.symlink_to(folder, target_is_directory=True)
        self.log.info("Created link: %s -> %s", candidate, folder)
        return candidate
