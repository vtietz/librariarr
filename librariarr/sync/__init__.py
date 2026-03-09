from .cleanup import ShadowCleanupManager
from .discovery import collect_current_links, discover_movie_folders
from .ingest import ShadowIngestor
from .linking import ShadowLinkManager
from .naming import MovieRef, canonical_name_from_folder, extract_title_year, parse_movie_ref

__all__ = [
    "MovieRef",
    "ShadowCleanupManager",
    "ShadowIngestor",
    "ShadowLinkManager",
    "canonical_name_from_folder",
    "collect_current_links",
    "discover_movie_folders",
    "extract_title_year",
    "parse_movie_ref",
]
