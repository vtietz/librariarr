from __future__ import annotations

import logging
import re

LOG = logging.getLogger("librariarr.service")
TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
IMDB_ID_RE = re.compile(r"\btt\d{5,10}\b", re.IGNORECASE)
IMDB_NEAR_TOKEN_RE = re.compile(r"(?:imdb)(?:id)?[^a-z0-9]{0,16}(tt\d{5,10})", re.IGNORECASE)
TMDB_ID_RE = re.compile(
    r"(?:tmdb|themoviedb)(?:id)?[^0-9]{0,16}(\d{2,})",
    re.IGNORECASE,
)
TMDB_UNIQUE_ID_RE = re.compile(
    r"<\s*uniqueid[^>]*type\s*=\s*[\"']tmdb[\"'][^>]*>\s*(\d{2,})\s*<",
    re.IGNORECASE,
)
TVDB_ID_RE = re.compile(
    r"(?:tvdb)(?:id)?[^0-9]{0,16}(\d{2,})",
    re.IGNORECASE,
)
TVDB_UNIQUE_ID_RE = re.compile(
    r"<\s*uniqueid[^>]*type\s*=\s*[\"']tvdb[\"'][^>]*>\s*(\d{2,})\s*<",
    re.IGNORECASE,
)
IMDB_UNIQUE_ID_RE = re.compile(
    r"<\s*uniqueid[^>]*type\s*=\s*[\"']imdb[\"'][^>]*>\s*(tt\d{5,10})\s*<",
    re.IGNORECASE,
)
