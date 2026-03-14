from __future__ import annotations

from pathlib import Path

import requests

from ..quality import map_quality_id
from ..sync import MovieRef, parse_movie_ref
from .common import (
    IMDB_ID_RE,
    IMDB_NEAR_TOKEN_RE,
    IMDB_UNIQUE_ID_RE,
    LOG,
    TITLE_TOKEN_RE,
    TMDB_ID_RE,
    TMDB_UNIQUE_ID_RE,
    TVDB_ID_RE,
    TVDB_UNIQUE_ID_RE,
)


class ServiceMatchingMixin:
    def _is_http_not_found(self, exc: requests.HTTPError) -> bool:
        response = exc.response
        return response is not None and response.status_code == 404

    def _match_movie_for_folder(
        self,
        folder: Path,
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
        movies_by_external_id: dict[str, dict],
        existing_links: set[Path],
    ) -> dict | None:
        external_id_match = self._match_movie_for_external_ids(folder, movies_by_external_id)
        if external_id_match is not None:
            return external_id_match

        ref = parse_movie_ref(folder.name)
        exact_match = movies_by_ref.get(ref) or movies_by_ref.get(
            MovieRef(title=ref.title, year=None)
        )
        if exact_match is not None:
            return exact_match

        link_match = self._match_movie_for_existing_links(
            existing_links,
            movies_by_ref,
            movies_by_path,
        )
        if link_match is not None:
            return link_match

        return self._fuzzy_match_movie_for_folder(ref, movies_by_ref)

    def _normalize_fs_path(self, value: str) -> str:
        return value.rstrip("/")

    def _match_movie_for_existing_links(
        self,
        existing_links: set[Path],
        movies_by_ref: dict[MovieRef, dict],
        movies_by_path: dict[str, dict],
    ) -> dict | None:
        for link in sorted(existing_links):
            linked_movie = movies_by_path.get(self._normalize_fs_path(str(link)))
            if linked_movie is not None:
                return linked_movie

            ref = parse_movie_ref(link.name.split("--", 1)[0])
            named_movie = movies_by_ref.get(ref) or movies_by_ref.get(
                MovieRef(title=ref.title, year=None)
            )
            if named_movie is not None:
                return named_movie

        return None

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
                score += 50

            if score > best_score:
                best_score = score
                best = movie

        return best if best_score > 0 else None

    def _build_movie_index(self) -> dict[MovieRef, dict]:
        index: dict[MovieRef, dict] = {}
        for movie in self.radarr.get_movies():
            self._index_movie(index=index, movie=movie)
        return index

    def _build_movie_path_index(self, movies_by_ref: dict[MovieRef, dict]) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)
            self._index_movie_path(index=index, movie=movie)
        return index

    def _build_movie_external_id_index(
        self,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict[str, dict]:
        index: dict[str, dict] = {}
        seen_ids: set[int] = set()
        for movie in movies_by_ref.values():
            movie_id = movie.get("id")
            if not isinstance(movie_id, int) or movie_id in seen_ids:
                continue
            seen_ids.add(movie_id)
            self._index_movie_external_ids(index=index, movie=movie)
        return index

    def _index_movie(self, index: dict[MovieRef, dict], movie: dict) -> None:
        title = (movie.get("title") or "").strip().lower()
        if not title:
            return
        year = movie.get("year")
        ref = MovieRef(title=title, year=year if isinstance(year, int) else None)
        index[ref] = movie
        if MovieRef(title=title, year=None) not in index:
            index[MovieRef(title=title, year=None)] = movie

    def _index_movie_path(self, index: dict[str, dict], movie: dict) -> None:
        path_raw = movie.get("path")
        path = str(path_raw).strip() if path_raw is not None else ""
        if not path:
            return
        index[self._normalize_fs_path(path)] = movie

    def _add_movie_id_if_present(self, target: set[int], movie: dict) -> int | None:
        movie_id = movie.get("id")
        if isinstance(movie_id, int):
            target.add(movie_id)
            return movie_id
        return None

    def _index_movie_external_ids(self, index: dict[str, dict], movie: dict) -> None:
        tmdb_id = movie.get("tmdbId")
        if isinstance(tmdb_id, int):
            index.setdefault(f"tmdb:{tmdb_id}", movie)

        imdb_raw = movie.get("imdbId")
        imdb_id = str(imdb_raw).strip().lower() if imdb_raw is not None else ""
        if imdb_id.startswith("tt"):
            index.setdefault(f"imdb:{imdb_id}", movie)

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

    def _extract_external_ids_from_text(self, text: str) -> tuple[int | None, str | None]:
        tmdb_id: int | None = None
        imdb_id: str | None = None

        tmdb_match = TMDB_UNIQUE_ID_RE.search(text) or TMDB_ID_RE.search(text)
        if tmdb_match is not None:
            try:
                tmdb_id = int(tmdb_match.group(1))
            except (TypeError, ValueError):
                tmdb_id = None

        imdb_match = (
            IMDB_UNIQUE_ID_RE.search(text)
            or IMDB_NEAR_TOKEN_RE.search(text)
            or IMDB_ID_RE.search(text)
        )
        if imdb_match is not None:
            imdb_id = (
                imdb_match.group(1).lower() if imdb_match.lastindex else imdb_match.group(0).lower()
            )

        return tmdb_id, imdb_id

    def _match_movie_for_external_ids(
        self,
        folder: Path,
        movies_by_external_id: dict[str, dict],
    ) -> dict | None:
        if not movies_by_external_id:
            return None

        identity_text = self._collect_folder_identity_text(folder)
        tmdb_id, imdb_id = self._extract_external_ids_from_text(identity_text)

        if tmdb_id is not None:
            tmdb_match = movies_by_external_id.get(f"tmdb:{tmdb_id}")
            if tmdb_match is not None:
                return tmdb_match

        if imdb_id is not None:
            return movies_by_external_id.get(f"imdb:{imdb_id}")

        return None

    def _sync_radarr_for_folder(
        self,
        folder: Path,
        link: Path,
        movie: dict,
        force_refresh: bool = False,
        apply_quality_mapping: bool = False,
    ) -> None:
        movie_id = movie.get("id")
        movie_title = movie.get("title")
        try:
            path_updated = self.radarr.update_movie_path(movie, str(link))
        except requests.HTTPError as exc:
            if self._is_http_not_found(exc):
                LOG.warning(
                    "Skipping Radarr sync for missing movie id=%s title=%s while updating path",
                    movie_id,
                    movie_title,
                )
                return
            raise

        quality_updated = False
        quality_map = self.config.effective_radarr_quality_map()
        if apply_quality_mapping and quality_map:
            quality_id = map_quality_id(
                folder,
                quality_map,
                use_nfo=self.config.analysis.use_nfo,
                use_media_probe=self.config.analysis.use_media_probe,
                media_probe_bin=self.config.analysis.media_probe_bin,
            )
            quality_updated = self.radarr.try_update_moviefile_quality(movie, quality_id)

        if force_refresh or path_updated or quality_updated:
            try:
                self.radarr.refresh_movie(int(movie["id"]), force=force_refresh)
            except requests.HTTPError as exc:
                if self._is_http_not_found(exc):
                    LOG.warning(
                        "Skipping Radarr refresh for missing movie id=%s title=%s",
                        movie_id,
                        movie_title,
                    )
                    return
                raise

    def _resolve_movie_for_link_name(
        self,
        link_name: str,
        movies_by_ref: dict[MovieRef, dict],
    ) -> dict | None:
        ref = parse_movie_ref(link_name.split("--", 1)[0])
        return movies_by_ref.get(ref) or movies_by_ref.get(MovieRef(title=ref.title, year=None))

    def _extract_tvdb_id_from_text(self, text: str) -> int | None:
        tvdb_match = TVDB_UNIQUE_ID_RE.search(text) or TVDB_ID_RE.search(text)
        if tvdb_match is None:
            return None
        try:
            return int(tvdb_match.group(1))
        except (TypeError, ValueError):
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

        identity_text = self._collect_folder_identity_text(folder)
        tvdb_id = self._extract_tvdb_id_from_text(identity_text)
        tmdb_id, imdb_id = self._extract_external_ids_from_text(identity_text)

        if tvdb_id is not None:
            tvdb_match = series_by_external_id.get(f"tvdb:{tvdb_id}")
            if tvdb_match is not None:
                return tvdb_match

        if tmdb_id is not None:
            tmdb_match = series_by_external_id.get(f"tmdb:{tmdb_id}")
            if tmdb_match is not None:
                return tmdb_match

        if imdb_id is not None:
            return series_by_external_id.get(f"imdb:{imdb_id}")

        return None

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
