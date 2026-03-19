from __future__ import annotations

from pathlib import Path

import requests

from ..sync import MovieRef, parse_movie_ref
from .common import LOG, TITLE_TOKEN_RE
from .external_id_parsing import (
    extract_external_ids_from_nfo,
    extract_external_ids_from_text,
    extract_tvdb_id_from_text,
)


class ServiceMatchingMixin:
    def _is_http_not_found(self, exc: requests.HTTPError) -> bool:
        response = exc.response
        return response is not None and response.status_code == 404

    def _normalize_fs_path(self, value: str) -> str:
        return value.rstrip("/")

    def _normalize_title_token(self, title: str) -> str:
        return TITLE_TOKEN_RE.sub("", title.strip().lower())

    def _fuzzy_match_movie_for_folder(
        self,
        ref: MovieRef,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        if ref.year is None:
            return None

        ref_norm = self._normalize_title_token(ref.title)
        if not ref_norm:
            return None

        best_score = -1
        best: dict | None = None
        seen_ids: set[int] = set()

        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)

            year = movie.get("year")
            if not isinstance(year, int) or year != ref.year:
                continue

            movie_title = str(movie.get("title") or "").strip()
            movie_norm = self._normalize_title_token(movie_title)
            if not movie_norm:
                continue

            score = 0
            if movie_norm == ref_norm:
                score += 100
            elif movie_norm in ref_norm or ref_norm in movie_norm:
                overlap = movie_norm if movie_norm in ref_norm else ref_norm
                if len(overlap) >= 5:
                    score += 50

            if score > best_score:
                best_score = score
                best = movie

        return best if best_score > 0 else None

    def _collect_folder_identity_text(self, folder: Path) -> str:
        parts = [folder.name]
        try:
            for child in sorted(folder.iterdir()):
                if not child.is_file():
                    continue

                parts.append(child.name)
                if child.suffix.lower() != ".nfo":
                    continue

                try:
                    parts.append(child.read_text(encoding="utf-8", errors="ignore"))
                except OSError:
                    continue
        except OSError:
            return " ".join(parts).lower()

        return " ".join(parts).lower()

    def _find_external_id_match(
        self,
        index: dict[str, dict],
        candidates: list[tuple[str, int | str]],
    ) -> dict | None:
        for kind, value in candidates:
            matched = index.get(f"{kind}:{value}")
            if matched is not None:
                return matched
        return None

    def _collect_nfo_external_ids(
        self,
        folder: Path,
    ) -> tuple[list[int], list[str], list[int]]:
        tmdb_ids: list[int] = []
        imdb_ids: list[str] = []
        tvdb_ids: list[int] = []

        def _add_unique(target: list[int | str], value: int | str | None) -> None:
            if value is None:
                return
            if value in target:
                return
            target.append(value)

        try:
            for child in sorted(folder.iterdir()):
                if not child.is_file() or child.suffix.lower() != ".nfo":
                    continue

                tmdb_id, imdb_id, tvdb_id = extract_external_ids_from_nfo(child)
                _add_unique(tmdb_ids, tmdb_id)
                _add_unique(imdb_ids, imdb_id)
                _add_unique(tvdb_ids, tvdb_id)
        except OSError:
            pass

        return tmdb_ids, imdb_ids, tvdb_ids

    def _extract_tvdb_id_from_text(self, text: str) -> int | None:
        return extract_tvdb_id_from_text(text)

    def _add_movie_id_if_present(self, target: set[int], movie: dict) -> int | None:
        movie_id = movie.get("id")
        if isinstance(movie_id, int):
            target.add(movie_id)
            return movie_id
        return None

    def _build_series_index(self) -> dict[MovieRef, dict]:
        index: dict[MovieRef, dict] = {}
        try:
            series_list = self.sonarr.get_series()
        except requests.RequestException as exc:
            self._log_sonarr_sync_config_hint(exc)
            LOG.warning(
                "Continuing reconcile without Sonarr series index due to request failure: %s",
                exc,
            )
            return index

        for series in series_list:
            self._index_series(index=index, series=series)
        return index

    def _build_series_indices(
        self,
    ) -> tuple[dict[MovieRef, dict], dict[str, dict], dict[str, dict]]:
        ref_index: dict[MovieRef, dict] = {}
        path_index: dict[str, dict] = {}
        ext_id_index: dict[str, dict] = {}
        try:
            series_list = self.sonarr.get_series()
        except requests.RequestException as exc:
            self._log_sonarr_sync_config_hint(exc)
            LOG.warning(
                "Continuing reconcile without Sonarr series index due to request failure: %s",
                exc,
            )
            return ref_index, path_index, ext_id_index

        for series in series_list:
            self._index_series(index=ref_index, series=series)
            self._index_series_path(index=path_index, series=series)
            self._index_series_external_ids(index=ext_id_index, series=series)
        return ref_index, path_index, ext_id_index

    def _build_series_path_index(self, series_by_ref: dict[MovieRef, dict]) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for series in series_by_ref.values():
            series_id = series.get("id")
            if not isinstance(series_id, int) or series_id in seen_ids:
                continue
            seen_ids.add(series_id)
            self._index_series_path(index=index, series=series)
        return index

    def _build_series_external_id_index(
        self,
        series_by_ref: dict[MovieRef, dict],
    ) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for series in series_by_ref.values():
            series_id = series.get("id")
            if not isinstance(series_id, int) or series_id in seen_ids:
                continue
            seen_ids.add(series_id)
            self._index_series_external_ids(index=index, series=series)
        return index

    def _index_series(self, index: dict[MovieRef, dict], series: dict) -> None:
        title = (series.get("title") or "").strip().lower()
        if not title:
            return
        year = series.get("year")
        ref = MovieRef(title=title, year=year if isinstance(year, int) else None)
        index[ref] = series
        if MovieRef(title=title, year=None) not in index:
            index[MovieRef(title=title, year=None)] = series

    def _index_series_path(self, index: dict[str, dict], series: dict) -> None:
        path_raw = series.get("path")
        path = str(path_raw).strip() if path_raw is not None else ""
        if not path:
            return
        index[self._normalize_fs_path(path)] = series

    def _index_series_external_ids(self, index: dict[str, dict], series: dict) -> None:
        tvdb_id = series.get("tvdbId")
        if isinstance(tvdb_id, int):
            index.setdefault(f"tvdb:{tvdb_id}", series)

        tmdb_id = series.get("tmdbId")
        if isinstance(tmdb_id, int):
            index.setdefault(f"tmdb:{tmdb_id}", series)

        imdb_raw = series.get("imdbId")
        imdb_id = str(imdb_raw).strip().lower() if imdb_raw is not None else ""
        if imdb_id.startswith("tt"):
            index.setdefault(f"imdb:{imdb_id}", series)

    def _match_series_for_external_ids(
        self,
        folder: Path,
        series_by_external_id: dict[str, dict],
    ) -> dict | None:
        if not series_by_external_id:
            return None

        nfo_tmdb_ids, nfo_imdb_ids, nfo_tvdb_ids = self._collect_nfo_external_ids(folder)
        nfo_candidates: list[tuple[str, int | str]] = [
            *[("tvdb", tvdb_id) for tvdb_id in nfo_tvdb_ids],
            *[("tmdb", tmdb_id) for tmdb_id in nfo_tmdb_ids],
            *[("imdb", imdb_id) for imdb_id in nfo_imdb_ids],
        ]
        nfo_match = self._find_external_id_match(series_by_external_id, nfo_candidates)
        if nfo_match is not None:
            return nfo_match

        identity_text = self._collect_folder_identity_text(folder)
        tvdb_id = self._extract_tvdb_id_from_text(identity_text)
        tmdb_id, imdb_id = extract_external_ids_from_text(identity_text)
        text_candidates: list[tuple[str, int | str]] = []
        if tvdb_id is not None:
            text_candidates.append(("tvdb", tvdb_id))
        if tmdb_id is not None:
            text_candidates.append(("tmdb", tmdb_id))
        if imdb_id is not None:
            text_candidates.append(("imdb", imdb_id))

        return self._find_external_id_match(series_by_external_id, text_candidates)

    def _match_series_for_existing_links(
        self,
        existing_links: set[Path],
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
    ) -> dict | None:
        for link in sorted(existing_links):
            linked_series = series_by_path.get(self._normalize_fs_path(str(link)))
            if linked_series is not None:
                return linked_series

            ref = parse_movie_ref(link.name.split("--", 1)[0])
            named_series = series_by_ref.get(ref) or series_by_ref.get(
                MovieRef(title=ref.title, year=None)
            )
            if named_series is not None:
                return named_series

        return None

    def _match_series_for_folder(
        self,
        folder: Path,
        series_by_ref: dict[MovieRef, dict],
        series_by_path: dict[str, dict],
        series_by_external_id: dict[str, dict],
        existing_links: set[Path],
    ) -> dict | None:
        external_id_match = self._match_series_for_external_ids(folder, series_by_external_id)
        if external_id_match is not None:
            return external_id_match

        ref = parse_movie_ref(folder.name)
        exact_match = series_by_ref.get(ref) or series_by_ref.get(
            MovieRef(title=ref.title, year=None)
        )
        if exact_match is not None:
            return exact_match

        link_match = self._match_series_for_existing_links(
            existing_links,
            series_by_ref,
            series_by_path,
        )
        if link_match is not None:
            return link_match

        return self._fuzzy_match_movie_for_folder(ref, series_by_ref)

    def _sync_sonarr_for_folder(
        self,
        _folder: Path,
        link: Path,
        series: dict,
        force_refresh: bool = False,
    ) -> None:
        series_id = series.get("id")
        series_title = series.get("title")
        try:
            path_updated = self.sonarr.update_series_path(series, str(link))
        except requests.HTTPError as exc:
            if self._is_http_not_found(exc):
                LOG.warning(
                    "Skipping Sonarr sync for missing series id=%s title=%s while updating path",
                    series_id,
                    series_title,
                )
                return
            self._log_sonarr_sync_config_hint(exc)
            LOG.warning(
                "Skipping Sonarr sync for series id=%s title=%s "
                "due to request failure while updating path: %s",
                series_id,
                series_title,
                exc,
            )
            return
        except requests.RequestException as exc:
            self._log_sonarr_sync_config_hint(exc)
            LOG.warning(
                "Skipping Sonarr sync for series id=%s title=%s "
                "due to request failure while updating path: %s",
                series_id,
                series_title,
                exc,
            )
            return

        if force_refresh or path_updated:
            try:
                self.sonarr.refresh_series(int(series["id"]), force=force_refresh)
            except requests.HTTPError as exc:
                if self._is_http_not_found(exc):
                    LOG.warning(
                        "Skipping Sonarr refresh for missing series id=%s title=%s",
                        series_id,
                        series_title,
                    )
                    return
                self._log_sonarr_sync_config_hint(exc)
                LOG.warning(
                    "Skipping Sonarr refresh for series id=%s title=%s due to request failure: %s",
                    series_id,
                    series_title,
                    exc,
                )
                return
            except requests.RequestException as exc:
                self._log_sonarr_sync_config_hint(exc)
                LOG.warning(
                    "Skipping Sonarr refresh for series id=%s title=%s due to request failure: %s",
                    series_id,
                    series_title,
                    exc,
                )
                return

    def _resolve_series_for_link_name(
        self,
        link_name: str,
        series_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        ref = parse_movie_ref(link_name.split("--", 1)[0])
        return series_by_ref.get(ref) or series_by_ref.get(MovieRef(title=ref.title, year=None))
