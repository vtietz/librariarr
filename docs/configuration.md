# Configuration Reference

Baseline: [config.yaml.example](../config.yaml.example). Env overrides:
`LIBRARIARR_RADARR_URL`, `LIBRARIARR_RADARR_API_KEY`, `LIBRARIARR_SONARR_URL`,
`LIBRARIARR_SONARR_API_KEY` (non-empty env wins over YAML).

## paths

| Key | Type | Notes |
|---|---|---|
| `movie_root_mappings[]` | list | `managed_root` (your curated tree) + `library_root` (Radarr root folder). Absolute, non-overlapping; one library per managed root. Required when Radarr is enabled. |
| `series_root_mappings[]` | list | `nested_root` (curated) + `shadow_root` (Sonarr root folder). Required when Sonarr is enabled. |
| `exclude_paths[]` | list | Case-insensitive patterns skipped by sync and discovery. `name/` matches a directory segment anywhere, `/abs/path` excludes a subtree, anything else is a filename glob. Defaults (`.deletedByLibrariarr/`, sample patterns, ...) are always appended. |

## radarr / sonarr

| Key | Default | Notes |
|---|---|---|
| `enabled` | radarr: presence of section, sonarr: `false` | |
| `url`, `api_key` | — | required when the section is present |
| `sync_enabled` | `true` | disable to keep the client configured but inactive |
| `refresh_debounce_seconds` | `15` | per-item Refresh command debounce |
| `auto_add_unmatched` | `false` | conservative auto-add: single exact title+year lookup match only |
| `auto_add_quality_profile_id` | unset | **required** for auto-add to act. Only affects LibrariArr's own auto-add path (a managed folder with no matching Arr entry) — normal Radarr/Sonarr-initiated adds pick their own profile and never consult this. The auto-added file already exists on disk, so the profile only governs *future* upgrade-search behavior, not what's already there. One value per Arr instance; no per-root-mapping override. |
| `auto_add_language_profile_id` | unset | Sonarr only, same scope as above |
| `auto_add_search_on_add` | `false` | if `true`, auto-add also triggers an immediate search (otherwise the existing file is just cataloged) |
| `auto_add_monitored` | `true` | |
| `auto_add_season_folder` | `true` | Sonarr only |
| `request_timeout_seconds` / `request_retry_attempts` / `request_retry_backoff_seconds` | 120/1/1.0 (radarr), 30/2/0.5 (sonarr) | HTTP client behavior |
| `projection.managed_video_extensions` | common video extensions | which files count as video |
| `projection.managed_extras_allowlist` | subtitles, nfo, poster, fanart | extras mirrored into library/shadow folders |

## runtime

| Key | Default | Notes |
|---|---|---|
| `debounce_seconds` | `8` | webhook burst debounce |
| `consistency_interval_seconds` | `300` | cheap pass; no tree walk (min 30) |
| `full_interval_minutes` | `60` | tree walk + discovery + prune (min 1) |
| `startup_scope` | `full` | `full` \| `consistency` \| `off` (quote `"off"` in YAML) |

## ingest

| Key | Default | Notes |
|---|---|---|
| `enabled` | `true` | disabling leaves new Arr imports library-only (warned) |
| `replacement_delete_mode` | `soft` | `soft` = quarantine superseded managed files under `<managed_root>/.deletedByLibrariarr/`; `hard` = delete |

## Environment Variables

| Variable | Purpose |
|---|---|
| `LIBRARIARR_CONFIG_PATH` | config path for `--web` (default `/config/config.yaml`) |
| `LIBRARIARR_STATE_PATH` | relocate the advisory id-cache (`librariarr-idcache.json`); default is next to the config file |
| `LIBRARIARR_WEBHOOK_SECRET` | if set, webhooks must send `X-Librariarr-Webhook-Secret` |
| `LIBRARIARR_UI_DIST` / `LIBRARIARR_UI_DEV_URL` | frontend assets location / dev redirect |
| `LIBRARIARR_WEB_HOST` / `LIBRARIARR_WEB_PORT` | server bind (default 0.0.0.0:8787) |

Unknown keys in config.yaml are ignored by the loader.
