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

        folder_canonical = shadow_root / canonical_name_from_folder(self._safe_link_name(folder))
        valid_links = self._valid_existing_links(folder, shadow_root, existing_links)
        for preferred_link in (folder_canonical, desired):
            if preferred_link in valid_links:
                return preferred_link, False

        if valid_links:
            return sorted(valid_links, key=str)[0], False

        created = not (desired.exists() or desired.is_symlink())
        link = self._create_link(folder, shadow_root, base_name)
        return link, created

    def _valid_existing_links(
        self,
        folder: Path,
        shadow_root: Path,
        existing_links: set[Path],
    ) -> set[Path]:
        valid_links: set[Path] = set()
        for link in existing_links:
            if link.parent != shadow_root or not link.exists() or not link.is_symlink():
                continue
            try:
                if link.resolve(strict=False) == folder:
                    valid_links.add(link)
            except OSError:
                continue
        return valid_links

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

    def _collision_qualifier(self, folder: Path, shadow_root: Path) -> str:
        shadow_root_name = self._normalize_name_part(shadow_root.name)
        for root in self.nested_roots:
            try:
                relative = folder.relative_to(root)
            except ValueError:
                continue

            parent_parts = [self._normalize_name_part(part) for part in relative.parts[:-1]]
            root_name = self._normalize_name_part(root.name)
            include_root_name = bool(root_name) and root_name != shadow_root_name
            qualifier_parts = ([root_name] if include_root_name else []) + parent_parts
            qualifier = "-".join(part for part in qualifier_parts if part)
            if qualifier:
                return qualifier
        return ""

    def _create_link(self, folder: Path, shadow_root: Path, base_name: str) -> Path:
        candidate = shadow_root / base_name
        qualifier = self._collision_qualifier(folder, shadow_root)
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
