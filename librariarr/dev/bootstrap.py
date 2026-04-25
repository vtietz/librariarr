from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import requests
import yaml

LOG = logging.getLogger("librariarr.dev.bootstrap")
CONFIG_PATH = Path("/config/config.yaml")
ENV_PATH = Path("/app/.env")
RADARR_CONFIG_XML = Path("/radarr-config/config.xml")
SONARR_CONFIG_XML = Path("/sonarr-config/config.xml")

DEFAULT_SERIES_ROOT_MAPPINGS = [
    {"nested_root": "/data/series", "shadow_root": "/data/sonarr_library"},
]

DEFAULT_MOVIE_ROOT_MAPPINGS = [
    {"managed_root": "/data/movies/age_06", "library_root": "/data/radarr_library/age_06"},
    {"managed_root": "/data/movies/age_12", "library_root": "/data/radarr_library/age_12"},
    {"managed_root": "/data/movies/age_16", "library_root": "/data/radarr_library/age_16"},
]


def _find_text_case_insensitive(root: ET.Element, expected_tag: str) -> str:
    for child in root.iter():
        if child.tag.lower() == expected_tag.lower() and child.text:
            return child.text.strip()
    return ""


def _wait_for_api_key(config_xml_path: Path, label: str, timeout_seconds: int = 240) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if config_xml_path.exists():
            try:
                root = ET.fromstring(config_xml_path.read_text(encoding="utf-8"))
                key = _find_text_case_insensitive(root, "ApiKey")
                if key:
                    LOG.info("Discovered %s API key from %s", label, config_xml_path)
                    return key
            except ET.ParseError:
                pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {label} API key in {config_xml_path}")


def _read_port_from_config_xml(config_xml_path: Path, default_port: int) -> int:
    if not config_xml_path.exists():
        return default_port

    try:
        root = ET.fromstring(config_xml_path.read_text(encoding="utf-8"))
    except ET.ParseError:
        return default_port

    port_text = _find_text_case_insensitive(root, "Port")
    if not port_text:
        return default_port

    try:
        return int(port_text)
    except ValueError:
        return default_port


def _arr_session(api_key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"X-Api-Key": api_key, "Content-Type": "application/json"})
    return session


def _wait_for_arr_api(
    base_url: str,
    session: requests.Session,
    label: str,
    timeout_seconds: int = 240,
    raise_on_timeout: bool = True,
) -> bool:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            response = session.get(f"{base_url}/api/v3/system/status", timeout=10)
            if response.status_code == 200:
                LOG.info("%s API is reachable", label)
                return True
            last_error = f"status={response.status_code} body={response.text[:200]}"
        except requests.RequestException as exc:
            last_error = str(exc)
        time.sleep(1)

    if raise_on_timeout:
        raise TimeoutError(f"Timed out waiting for {label} API at {base_url}: {last_error}")
    return False


def _set_if_present(payload: dict[str, Any], key: str, value: Any) -> bool:
    if key not in payload:
        return False
    if payload.get(key) == value:
        return False
    payload[key] = value
    return True


def _update_host_config(
    base_url: str,
    session: requests.Session,
    label: str,
    expected_port: int,
) -> None:
    response = session.get(f"{base_url}/api/v3/config/host", timeout=15)
    response.raise_for_status()
    current = response.json()
    if not isinstance(current, dict):
        LOG.warning("Skipping %s host config update: unexpected payload type", label)
        return

    updated = dict(current)
    changed = False

    changed |= _set_if_present(updated, "enableSsl", False)
    changed |= _set_if_present(updated, "sslEnabled", False)
    changed |= _set_if_present(updated, "port", expected_port)

    auth_method = updated.get("authenticationMethod")
    if isinstance(auth_method, str) and auth_method != "None":
        updated["authenticationMethod"] = "None"
        changed = True

    auth_required = updated.get("authenticationRequired")
    if isinstance(auth_required, str) and auth_required != "DisabledForLocalAddresses":
        updated["authenticationRequired"] = "DisabledForLocalAddresses"
        changed = True

    if not changed:
        LOG.info("%s host settings already aligned (auth/https)", label)
        return

    put_response = session.put(f"{base_url}/api/v3/config/host", json=updated, timeout=15)
    put_response.raise_for_status()
    LOG.info("Updated %s host settings (auth disabled, https disabled)", label)


def _normalize_path(path: str) -> str:
    normalized = path.strip().rstrip("/")
    return normalized if normalized else "/"


_RADARR_MANAGED_ROOT = "/data/movies"
_SONARR_MANAGED_ROOT = "/data/series"

DEV_MOVIES = [
    {"title": "Toy Story", "year": 1995, "tmdbId": 862, "root": f"{_RADARR_MANAGED_ROOT}/age_06"},
]

DEV_SERIES = [
    {"title": "Bluey", "year": 2018, "tvdbId": 354974, "root": f"{_SONARR_MANAGED_ROOT}/age_06"},
]


def _seed_arr_entries(
    radarr_url: str,
    radarr_session: requests.Session,
    sonarr_url: str,
    sonarr_session: requests.Session,
) -> None:
    """Add well-known movies/series directly to Radarr/Sonarr via their APIs."""
    try:
        _seed_radarr_movies(radarr_url, radarr_session)
    except Exception:
        LOG.warning("Failed to seed Radarr movies — continuing", exc_info=True)

    try:
        _seed_sonarr_series(sonarr_url, sonarr_session)
    except Exception:
        LOG.warning("Failed to seed Sonarr series — continuing", exc_info=True)


def _seed_radarr_movies(base_url: str, session: requests.Session) -> None:
    profiles_resp = session.get(f"{base_url}/api/v3/qualityprofile", timeout=15)
    profiles_resp.raise_for_status()
    profiles = profiles_resp.json()
    if not profiles:
        LOG.warning("Radarr has no quality profiles — skipping movie seeding")
        return
    quality_profile_id: int = profiles[0]["id"]

    movies_resp = session.get(f"{base_url}/api/v3/movie", timeout=15)
    movies_resp.raise_for_status()
    existing_tmdb_ids: set[int] = {
        m["tmdbId"] for m in movies_resp.json() if isinstance(m, dict) and "tmdbId" in m
    }

    for entry in DEV_MOVIES:
        if entry["tmdbId"] in existing_tmdb_ids:
            LOG.info(
                "Radarr already has %s (tmdbId=%s) — skipping",
                entry["title"],
                entry["tmdbId"],
            )
            continue

        payload = {
            "title": entry["title"],
            "year": entry["year"],
            "tmdbId": entry["tmdbId"],
            "rootFolderPath": entry["root"],
            "qualityProfileId": quality_profile_id,
            "monitored": False,
            "addOptions": {"searchForMovie": False},
        }
        resp = session.post(f"{base_url}/api/v3/movie", json=payload, timeout=15)
        if resp.status_code >= 400:
            LOG.warning(
                "Failed to add %s to Radarr (status=%s body=%s)",
                entry["title"],
                resp.status_code,
                resp.text[:200],
            )
            continue
        LOG.info("Added %s (tmdbId=%s) to Radarr", entry["title"], entry["tmdbId"])


def _seed_sonarr_series(base_url: str, session: requests.Session) -> None:
    profiles_resp = session.get(f"{base_url}/api/v3/qualityprofile", timeout=15)
    profiles_resp.raise_for_status()
    profiles = profiles_resp.json()
    if not profiles:
        LOG.warning("Sonarr has no quality profiles — skipping series seeding")
        return
    quality_profile_id: int = profiles[0]["id"]

    language_profile_id: int | None = None
    try:
        lang_resp = session.get(f"{base_url}/api/v3/languageprofile", timeout=15)
        if lang_resp.status_code == 200:
            lang_profiles = lang_resp.json()
            if lang_profiles:
                language_profile_id = lang_profiles[0]["id"]
    except Exception:
        LOG.debug("Language profiles not available — omitting from payload")

    series_resp = session.get(f"{base_url}/api/v3/series", timeout=15)
    series_resp.raise_for_status()
    existing_tvdb_ids: set[int] = {
        s["tvdbId"] for s in series_resp.json() if isinstance(s, dict) and "tvdbId" in s
    }

    for entry in DEV_SERIES:
        if entry["tvdbId"] in existing_tvdb_ids:
            LOG.info(
                "Sonarr already has %s (tvdbId=%s) — skipping",
                entry["title"],
                entry["tvdbId"],
            )
            continue

        payload: dict[str, Any] = {
            "title": entry["title"],
            "year": entry["year"],
            "tvdbId": entry["tvdbId"],
            "rootFolderPath": entry["root"],
            "qualityProfileId": quality_profile_id,
            "monitored": False,
            "seasonFolder": True,
            "addOptions": {"searchForMissingEpisodes": False},
        }
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id

        resp = session.post(f"{base_url}/api/v3/series", json=payload, timeout=15)
        if resp.status_code >= 400:
            LOG.info(
                "Sonarr rejected %s (tvdbId=%s) — this is expected on fresh instances "
                "where TVDB metadata has not synced yet (status=%s)",
                entry["title"],
                entry["tvdbId"],
                resp.status_code,
            )
            continue
        LOG.info("Added %s (tvdbId=%s) to Sonarr", entry["title"], entry["tvdbId"])


def _ensure_root_folders(
    base_url: str,
    session: requests.Session,
    label: str,
    root_paths: list[str],
) -> None:
    response = session.get(f"{base_url}/api/v3/rootfolder", timeout=15)
    response.raise_for_status()
    raw = response.json()
    folders = raw if isinstance(raw, list) else []
    existing = {
        _normalize_path(str(item.get("path", "")))
        for item in folders
        if isinstance(item, dict) and item.get("path")
    }

    for root_path in root_paths:
        normalized = _normalize_path(root_path)
        if normalized in existing:
            continue

        post_response = session.post(
            f"{base_url}/api/v3/rootfolder",
            json={"path": root_path},
            timeout=15,
        )
        if post_response.status_code >= 400:
            LOG.warning(
                "Unable to add %s root folder %s (status=%s body=%s)",
                label,
                root_path,
                post_response.status_code,
                post_response.text[:200],
            )
            continue

        LOG.info("Added %s root folder: %s", label, root_path)


def _ensure_container_paths(
    mappings: list[dict[str, Any]],
    keys: tuple[str, ...] = ("nested_root", "shadow_root"),
) -> None:
    for mapping in mappings:
        for key in keys:
            path_text = str(mapping.get(key, "")).strip()
            if not path_text.startswith("/data/"):
                continue
            try:
                Path(path_text).mkdir(parents=True, exist_ok=True)
            except PermissionError:
                LOG.warning(
                    "Skipping directory creation for %s due to permission constraints",
                    path_text,
                )


def _is_non_empty_mapping_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, dict) for item in value)


def _ensure_dev_sonarr_mappings(
    series_root_mappings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_pairs: set[tuple[str, str]] = set()
    radarr_candidates: list[tuple[str, str]] = []
    has_sonarr_mapping = False

    for mapping in series_root_mappings:
        nested_root = str(mapping.get("nested_root", "")).strip()
        shadow_root = str(mapping.get("shadow_root", "")).strip()
        if not nested_root or not shadow_root:
            continue

        existing_pairs.add((nested_root, shadow_root))
        shadow_lower = shadow_root.lower()
        nested_lower = nested_root.lower()
        if "sonarr" in shadow_lower:
            has_sonarr_mapping = True
        if "radarr" in shadow_lower or "/movies" in nested_lower:
            radarr_candidates.append((nested_root, shadow_root))

    if has_sonarr_mapping:
        return series_root_mappings

    additions: list[dict[str, str]] = []
    for nested_root, shadow_root in radarr_candidates:
        sonarr_nested = nested_root.replace("/movies/", "/series/").replace("/movies", "/series")
        sonarr_shadow = shadow_root.replace(
            "/radarr_library/",
            "/sonarr_library/",
        ).replace("/radarr_library", "/sonarr_library")
        if sonarr_nested == nested_root and sonarr_shadow == shadow_root:
            continue

        mapped_pair = (sonarr_nested, sonarr_shadow)
        if mapped_pair in existing_pairs:
            continue
        existing_pairs.add(mapped_pair)
        additions.append({"nested_root": sonarr_nested, "shadow_root": sonarr_shadow})

    if not additions and ("/data/series", "/data/sonarr_library") not in existing_pairs:
        additions.append({"nested_root": "/data/series", "shadow_root": "/data/sonarr_library"})

    if additions:
        series_root_mappings.extend(additions)
        LOG.info("Added %s Sonarr root mapping(s) for dev mode", len(additions))

    return series_root_mappings


def _query_arr_ids(
    base_url: str,
    session: requests.Session,
    label: str,
) -> dict[str, set[int]]:
    ids: dict[str, set[int]] = {
        "quality_profile_ids": set(),
        "quality_definition_ids": set(),
        "custom_format_ids": set(),
        "language_profile_ids": set(),
    }

    def _fetch_ids(endpoint: str, key: str) -> set[int]:
        try:
            resp = session.get(f"{base_url}/api/v3/{endpoint}", timeout=15)
            if resp.status_code == 404:
                return set()
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return {item["id"] for item in data if isinstance(item, dict) and "id" in item}
        except Exception:
            LOG.warning("Failed to query %s %s — skipping", label, endpoint)
        return set()

    if "radarr" in label.lower():
        ids["quality_profile_ids"] = _fetch_ids("qualityprofile", "quality_profile_ids")
        ids["quality_definition_ids"] = _fetch_ids("qualitydefinition", "quality_definition_ids")
        ids["custom_format_ids"] = _fetch_ids("customformat", "custom_format_ids")
    elif "sonarr" in label.lower():
        ids["quality_profile_ids"] = _fetch_ids("qualityprofile", "quality_profile_ids")
        ids["language_profile_ids"] = _fetch_ids("languageprofile", "language_profile_ids")

    return ids


def _filter_mapping_list(
    mapping_section: dict[str, Any],
    list_key: str,
    id_key: str,
    valid_ids: set[int],
    label: str,
) -> None:
    entries = mapping_section.get(list_key)
    if not isinstance(entries, list):
        return
    kept: list[Any] = []
    for entry in entries:
        if not isinstance(entry, dict) or entry.get(id_key) in valid_ids:
            kept.append(entry)
        else:
            LOG.info("Removed %s %s entry with %s=%s", label, list_key, id_key, entry.get(id_key))
    mapping_section[list_key] = kept


def _repair_mapping_ids(
    payload: dict[str, Any],
    radarr_ids: dict[str, set[int]],
    sonarr_ids: dict[str, set[int]],
) -> None:
    radarr_mapping = payload.get("radarr", {}).get("mapping", {})
    if isinstance(radarr_mapping, dict):
        _filter_mapping_list(
            radarr_mapping,
            "custom_format_map",
            "format_id",
            radarr_ids["custom_format_ids"],
            "Radarr",
        )
        _filter_mapping_list(
            radarr_mapping,
            "quality_map",
            "target_id",
            radarr_ids["quality_definition_ids"],
            "Radarr",
        )

    sonarr_mapping = payload.get("sonarr", {}).get("mapping", {})
    if isinstance(sonarr_mapping, dict):
        _filter_mapping_list(
            sonarr_mapping,
            "quality_profile_map",
            "profile_id",
            sonarr_ids["quality_profile_ids"],
            "Sonarr",
        )
        _filter_mapping_list(
            sonarr_mapping,
            "language_profile_map",
            "profile_id",
            sonarr_ids["language_profile_ids"],
            "Sonarr",
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        return raw
    return {}


def _save_yaml(path: Path, payload: dict[str, Any]) -> None:
    backup_path = path.with_name(f"{path.name}.bak")
    if path.exists():
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _sync_env_file(
    radarr_url: str,
    sonarr_url: str,
    radarr_api_key: str,
    sonarr_api_key: str,
) -> None:
    lines: list[str]
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    desired_values = {
        "LIBRARIARR_DEV_RADARR_URL": radarr_url,
        "LIBRARIARR_DEV_SONARR_URL": sonarr_url,
        "LIBRARIARR_RADARR_API_KEY": radarr_api_key,
        "LIBRARIARR_SONARR_API_KEY": sonarr_api_key,
    }

    for key, value in desired_values.items():
        replaced = False
        prefix = f"{key}="
        for index, line in enumerate(lines):
            if line.startswith(prefix):
                lines[index] = f"{key}={value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    LOG.info("Synchronized %s with dev Arr URLs and API keys", ENV_PATH)


def _sync_config_yaml(
    radarr_url: str,
    sonarr_url: str,
    radarr_api_key: str,
    sonarr_api_key: str,
    radarr_ids: dict[str, set[int]] | None = None,
    sonarr_ids: dict[str, set[int]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    payload = _load_yaml(CONFIG_PATH)

    radarr_section = payload.setdefault("radarr", {})
    sonarr_section = payload.setdefault("sonarr", {})
    paths_section = payload.setdefault("paths", {})

    series_root_mappings = paths_section.get("series_root_mappings")
    if not _is_non_empty_mapping_list(series_root_mappings):
        series_root_mappings = list(DEFAULT_SERIES_ROOT_MAPPINGS)
    else:
        series_root_mappings = [item for item in series_root_mappings if isinstance(item, dict)]

    series_root_mappings = _ensure_dev_sonarr_mappings(series_root_mappings)
    paths_section["series_root_mappings"] = series_root_mappings

    movie_root_mappings = paths_section.get("movie_root_mappings")
    if not _is_non_empty_mapping_list(movie_root_mappings):
        movie_root_mappings = list(DEFAULT_MOVIE_ROOT_MAPPINGS)
    else:
        movie_root_mappings = [item for item in movie_root_mappings if isinstance(item, dict)]
    paths_section["movie_root_mappings"] = movie_root_mappings

    radarr_section["enabled"] = True
    radarr_section["sync_enabled"] = True
    radarr_section["url"] = radarr_url
    radarr_section["api_key"] = radarr_api_key

    sonarr_section["enabled"] = True
    sonarr_section["sync_enabled"] = True
    sonarr_section["url"] = sonarr_url
    sonarr_section["api_key"] = sonarr_api_key

    if radarr_ids is not None and sonarr_ids is not None:
        _repair_mapping_ids(payload, radarr_ids, sonarr_ids)

    _save_yaml(CONFIG_PATH, payload)
    LOG.info("Synchronized %s with dev Arr URLs and API keys", CONFIG_PATH)

    return (
        [item for item in series_root_mappings if isinstance(item, dict)],
        [item for item in movie_root_mappings if isinstance(item, dict)],
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    radarr_api_key = _wait_for_api_key(RADARR_CONFIG_XML, "Radarr")
    sonarr_api_key = _wait_for_api_key(SONARR_CONFIG_XML, "Sonarr")

    radarr_configured_port = _read_port_from_config_xml(RADARR_CONFIG_XML, default_port=7878)
    sonarr_configured_port = _read_port_from_config_xml(SONARR_CONFIG_XML, default_port=8989)

    radarr_bootstrap_url = f"http://radarr-dev:{radarr_configured_port}"
    sonarr_bootstrap_url = f"http://sonarr-dev:{sonarr_configured_port}"

    radarr_session = _arr_session(radarr_api_key)
    sonarr_session = _arr_session(sonarr_api_key)

    _wait_for_arr_api(radarr_bootstrap_url, radarr_session, "Radarr")
    _wait_for_arr_api(sonarr_bootstrap_url, sonarr_session, "Sonarr")

    _update_host_config(
        radarr_bootstrap_url,
        radarr_session,
        "Radarr",
        expected_port=7878,
    )
    _update_host_config(
        sonarr_bootstrap_url,
        sonarr_session,
        "Sonarr",
        expected_port=8989,
    )

    radarr_effective_url = radarr_bootstrap_url
    sonarr_effective_url = sonarr_bootstrap_url

    radarr_ids = _query_arr_ids(radarr_effective_url, radarr_session, "Radarr")
    sonarr_ids = _query_arr_ids(sonarr_effective_url, sonarr_session, "Sonarr")

    series_root_mappings, movie_root_mappings = _sync_config_yaml(
        radarr_url=radarr_effective_url,
        sonarr_url=sonarr_effective_url,
        radarr_api_key=radarr_api_key,
        sonarr_api_key=sonarr_api_key,
        radarr_ids=radarr_ids,
        sonarr_ids=sonarr_ids,
    )
    _ensure_container_paths(series_root_mappings)
    _ensure_container_paths(movie_root_mappings, keys=("managed_root", "library_root"))

    radarr_roots = [
        str(m.get("managed_root", "")).strip()
        for m in movie_root_mappings
        if str(m.get("managed_root", "")).strip()
    ] or ["/data/movies"]
    sonarr_roots = [
        str(m.get("nested_root", "")).strip()
        for m in series_root_mappings
        if str(m.get("nested_root", "")).strip()
    ] or ["/data/series"]

    _sync_env_file(
        radarr_url=radarr_effective_url,
        sonarr_url=sonarr_effective_url,
        radarr_api_key=radarr_api_key,
        sonarr_api_key=sonarr_api_key,
    )

    _ensure_root_folders(radarr_effective_url, radarr_session, "Radarr", radarr_roots)
    _ensure_root_folders(sonarr_effective_url, sonarr_session, "Sonarr", sonarr_roots)

    _seed_arr_entries(
        radarr_url=radarr_effective_url,
        radarr_session=radarr_session,
        sonarr_url=sonarr_effective_url,
        sonarr_session=sonarr_session,
    )

    LOG.info("Dev bootstrap completed")


if __name__ == "__main__":
    main()
