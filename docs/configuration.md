# Configuration Guide

Use `config.yaml.example` as your starting point.

This page is the detailed reference for all `config.yaml` options.

For end-to-end lifecycle behavior examples, see `docs/workflows.md`.

## Quick Start

Recommended baseline:

```yaml
paths:
  movie_root_mappings:
    - managed_root: "/data/radarr_library/age_06"
      library_root: "/data/movies/age_06"
  # Required only when sonarr.enabled=true
  root_mappings:
    - nested_root: "/data/series/age_06"       # Sonarr managed root
      shadow_root: "/data/sonarr_library/age_06" # Sonarr projection library root
  exclude_paths:
    - ".deletedByTMM/"
    - ".actors/"
    - ".librariarr/**"

radarr:
  enabled: true
  url: "http://radarr:7878"
  api_key: "YOUR_API_KEY"
  sync_enabled: true
  refresh_debounce_seconds: 15
  request_timeout_seconds: 30
  request_retry_attempts: 2
  request_retry_backoff_seconds: 0.5
  auto_add_unmatched: true
  auto_add_search_on_add: false
  mapping:
    quality_map:
      - match: ["2160p", "x265"]
        target_id: 19
      - match: ["1080p", "x265"]
        target_id: 7
      - match: ["1080p"]
        target_id: 9
      - match: ["720p"]
        target_id: 5
    custom_format_map:
      - match: ["german"]
        format_id: 42
      - match: ["2160p", "x265"]
        format_id: 99

sonarr:
  enabled: false
  url: "http://sonarr:8989"
  api_key: "YOUR_API_KEY"
  sync_enabled: true
  refresh_debounce_seconds: 15
  request_timeout_seconds: 30
  request_retry_attempts: 2
  request_retry_backoff_seconds: 0.5
  auto_add_unmatched: false
  auto_add_search_on_add: false
  projection:
    series_folder_name_source: "managed"
    managed_video_extensions: [".mkv", ".mp4", ".avi"]
    managed_extras_allowlist: ["*.srt", "series.nfo", "tvshow.nfo"]
  mapping:
    quality_profile_map:
      - match: ["2160p", "x265"]
        profile_id: 12
    language_profile_map:
      - match: ["german", "lang-de"]
        profile_id: 4

ingest:
  enabled: true
  min_age_seconds: 300
  collision_policy: "qualify"

analysis:
  use_nfo: false
  use_media_probe: true
```

## Example Notes

`config.yaml.example` is intentionally brief. Use this section for the longer rationale:

- `radarr.auto_add_unmatched=true` is enabled in the example for out-of-the-box automation. Disable it if source folder names are often temporary or incomplete.
- `radarr.enabled=false` disables movie projection and Radarr integration entirely (useful for Sonarr-only setups).
- `sonarr.enabled=true` enables Sonarr projection (managed roots to library roots).
- `sonarr.projection.series_folder_name_source=managed` preserves managed relative folder names in the Sonarr library root.
- `radarr.refresh_debounce_seconds=15` helps avoid duplicate `RefreshMovie` bursts for the same movie during noisy event windows; set `0` to disable.
- `sonarr.refresh_debounce_seconds=15` helps avoid duplicate `RefreshSeries` bursts during noisy rename windows.
- Keep `radarr.auto_add_search_on_add=false` unless you explicitly want immediate indexer searches after auto-add.
- Leave `radarr.auto_add_quality_profile_id` unset to use automatic profile mapping. Set it only when you want strict, fixed-profile behavior.
- `ingest.*` settings are retained for compatibility but are no longer part of the active projection reconcile path.
- `radarr.mapping.custom_format_map` is optional and useful when Radarr parse cannot infer enough custom-format signal from release title alone.
- Keep `radarr.mapping.quality_map` short if you use it as fallback; start with resolution and codec signals.
- Enable `analysis.use_media_probe=true` for more reliable quality detection when filenames are inconsistent.
- On startup preflight, LibrariArr logs configured Radarr/Sonarr mapping ids and catalogs (`id:name`) to make id verification easier.
- Top-level `quality_map` / `custom_format_map` is not supported; use `radarr.mapping.*` only.

## How It Fits Together

Configuration interaction for auto-add/profile behavior:

1. If `radarr.auto_add_quality_profile_id` is set, that fixed profile is always used.
2. If it is not set, LibrariArr first uses custom-format signal from Radarr parse and local `radarr.mapping.custom_format_map`.
3. If no custom-format signal is available, LibrariArr tries parse-derived quality-definition signal from Radarr (`quality`/`qualityDefinition`).
4. If there is still no parse quality signal (or it does not map), LibrariArr falls back to `radarr.mapping.quality_map`.
5. If neither mapping path yields a profile, LibrariArr falls back to the lowest available Radarr profile id.
6. `analysis.use_nfo` and `analysis.use_media_probe` feed token extraction for both `radarr.mapping.custom_format_map` and `radarr.mapping.quality_map` matching.
7. `radarr.mapping.quality_map` is optional and can be short (or empty) when you primarily rely on custom-format-based mapping.

Projection strategy for Arr identity:
1. Radarr projection uses Radarr movie inventory (`/api/v3/movie`) and `paths.movie_root_mappings`.
2. Sonarr projection uses Sonarr series inventory (`/api/v3/series`) and `paths.root_mappings`.
3. Optional webhook queues scope projection to affected movie/series ids.

Why Radarr parse is title-based:
- Radarr `/api/v3/parse` accepts a `title` parameter, so parse-based custom format detection is driven by folder/file title strings.
- LibrariArr tries multiple title candidates (folder name, video stem, video filename), not only one title string.
- Parse output can also include quality-definition signal, which LibrariArr can use as a fallback for profile mapping.
- Deeper local analysis (NFO + ffprobe + filename tokens) can still influence profile selection, but custom-format-based influence requires `radarr.mapping.custom_format_map` because token-level signals do not map to Radarr custom format IDs automatically.

## Multiple Versions & Constraints

Important limitation when using a single Radarr/Sonarr instance:

- Radarr and Sonarr identify items by media identity (movie/series metadata), not by filesystem folder uniqueness alone.
- In practice, this means one managed item has one canonical managed path at a time.
- If your source tree contains multiple parallel versions of the same movie/series (for example theatrical + director's cut as separate folders), discovery can see both, but Arr-side identity still collides.
- Result: only one path can be the effective managed path for that Arr item, and alternates are treated as duplicates/noise for syncing.

Why this happens:

- LibrariArr matches folders to Arr records by identity signals (title/year, ids), then syncs that Arr record path to the selected shadow link.
- Separate folder names or deeper nesting do not create separate Arr identities by themselves.

Recommended patterns:

1. Keep exactly one canonical version inside Arr-managed roots.
2. Keep alternate versions outside Arr-managed roots, or
3. Exclude alternate-version folders from discovery using `paths.exclude_paths`.

### Excluding Alternate Versions (Workaround)

Yes — this is the recommended workaround when you intentionally keep multiple versions on disk.

`paths.exclude_paths` uses **glob-style patterns** (gitignore-like), not full regex. This is usually enough to filter alternate-version folders.

Examples:

```yaml
paths:
  exclude_paths:
    # common alternate-version naming patterns
    - "**/*Director's Cut*/"
    - "**/*Extended*/"
    - "**/*Remastered*/"
    - "**/*Theatrical*/"

    # keep discovery away from known side-content folders
    - "**/Specials/"
    - "**/Extras/"
```

Notes:

- Matching is case-insensitive in discovery.
- Use `/` suffix to target directories only.
- Use `**` to match at any depth below each `nested_root`.

## Paths

`paths.movie_root_mappings`:
- Each Radarr-managed source root (`managed_root`) maps to one curated movie target (`library_root`).
- Used by the movie projection pipeline.

`paths.root_mappings`:
- Sonarr projection mappings (`nested_root` -> `shadow_root`).
- Required when `sonarr.enabled=true`.
- `nested_root` is Sonarr-managed source root.
- `shadow_root` is Sonarr projection library target root.

`paths.exclude_paths`:
- Optional list of glob-style ignore patterns applied during movie/series discovery.
- Patterns are evaluated relative to each `nested_root` (gitignore-style intent).
- Useful for skipping transient/trash trees such as `.deletedByTMM/`.
- Supports `*` and `**` globs, and comments/blank entries are ignored.

## Radarr

`radarr.enabled`:
- Enables movie projection and Radarr integration flow.
- If false, movie projection is skipped.

`radarr.url`:
- Radarr base URL (for example `http://radarr:7878`).

`radarr.api_key`:
- Radarr API key.

`radarr.sync_enabled`:
- Controls Radarr sync/preflight behaviors around auxiliary Radarr sync checks.
- Movie projection still relies on Radarr movie inventory when `radarr.enabled=true`.

`radarr.refresh_debounce_seconds`:
- Debounce window for `RefreshMovie` commands per movie id.
- Default is `15` seconds.
- Set `0` to disable debounce.

`radarr.request_timeout_seconds`:
- Per-request timeout in seconds for Radarr API calls.
- Default is `30`.

`radarr.request_retry_attempts`:
- Number of retries for transient request failures.
- Default is `2`.
- Applies only to idempotent methods (`GET`, `PUT`, `DELETE`, `HEAD`, `OPTIONS`).

`radarr.request_retry_backoff_seconds`:
- Exponential backoff base delay between retries.
- Delay pattern: `base * 2^attempt`.
- Default is `0.5`.

`radarr.auto_add_unmatched`:
- If true, unmatched folders can be auto-added to Radarr.
- Recommended for normal automation.
- Disable if your source folder names are frequently temporary/incomplete.
- Auto-add still converges to folder-derived managed link paths.

`radarr.auto_add_quality_profile_id`:
- Optional fixed quality profile id for auto-add.
- If set, this profile id is always used for newly auto-added movies.
- If omitted, LibrariArr maps automatically using this workflow:
  1. Try Radarr parse (`/api/v3/parse`) on folder/file titles and collect matched `customFormats`.
  2. Add optional local `radarr.mapping.custom_format_map` matches from filename/folder text, optional NFO, and optional ffprobe tokens.
  3. Score Radarr profiles by `formatItems` scores and select the best profile.
  4. If there is still no custom-format signal, try parse-derived quality-definition fallback.
  5. If parse quality is unavailable or cannot be mapped, use `radarr.mapping.quality_map` fallback scoring (`target_id` against profile cutoffs/allowed qualities).
  6. If no profile can be mapped from either signal, fall back to the lowest available profile id.
  7. If multiple profiles tie, prefer specific profile names over generic profiles (`Any`, `All`, `Default`).

`radarr.auto_add_search_on_add`:
- If true, Radarr starts indexer search immediately after add.
- Keep false if you only want registration/path import behavior.

`radarr.auto_add_monitored`:
- Initial Radarr monitored flag for newly auto-added entries.

## Sonarr

`sonarr.enabled`:
- Enables Sonarr projection and Sonarr integration flow.

`sonarr.url`:
- Sonarr base URL (for example `http://sonarr:8989`).

`sonarr.api_key`:
- Sonarr API key.

`sonarr.sync_enabled`:
- Enables Sonarr API projection interactions.
- If false while `sonarr.enabled=true`, Sonarr projection is skipped.

`sonarr.refresh_debounce_seconds`:
- Debounce window for `RefreshSeries` commands per series id.
- Default is `15` seconds.
- Set `0` to disable debounce.

`sonarr.request_timeout_seconds`:
- Per-request timeout in seconds for Sonarr API calls.
- Default is `30`.

`sonarr.request_retry_attempts`:
- Number of retries for transient request failures.
- Default is `2`.
- Applies only to idempotent methods (`GET`, `PUT`, `DELETE`, `HEAD`, `OPTIONS`).

`sonarr.request_retry_backoff_seconds`:
- Exponential backoff base delay between retries.
- Delay pattern: `base * 2^attempt`.
- Default is `0.5`.

`sonarr.auto_add_unmatched`:
- Legacy compatibility field; not part of the active projection reconcile path.

`sonarr.auto_add_quality_profile_id`:
- Legacy compatibility field; not part of the active projection reconcile path.

`sonarr.auto_add_language_profile_id`:
- Legacy compatibility field; not part of the active projection reconcile path.

`sonarr.auto_add_search_on_add`:
- Legacy compatibility field; not part of the active projection reconcile path.

`sonarr.auto_add_monitored`:
- Legacy compatibility field; not part of the active projection reconcile path.

`sonarr.auto_add_season_folder`:
- Legacy compatibility field; not part of the active projection reconcile path.

`sonarr.projection.series_folder_name_source`:
- `managed`: keep managed relative path under `shadow_root`.
- `sonarr`: use Sonarr title/year naming.

`sonarr.projection.managed_video_extensions`:
- Extensions treated as managed episode/video files for Sonarr projection.

`sonarr.projection.managed_extras_allowlist`:
- Allowlisted extras (for example subtitles or NFO files) projected with episodes.

## Mapping

`radarr.mapping.quality_map` rules:
- Optional fallback map (can be empty).
- Checked top-to-bottom.
- All tokens in `match` must be present (AND logic).
- First match wins.
- If no match, fallback quality definition id is `4`.

`radarr.mapping.custom_format_map` rules:
- Optional and additive (all matching rules are collected).
- Uses the same token sources as quality mapping: filename/folder text, optional NFO, optional ffprobe tokens.
- `format_id` must be a valid Radarr custom format id.
- Helps preserve deeper local analysis signals (for example language/audio hints) when Radarr parse relies mostly on release title text.
- Without `radarr.mapping.custom_format_map`, deeper analytics still run for `radarr.mapping.quality_map`, but they do not create Radarr custom format IDs on their own.

`sonarr.mapping.quality_profile_map` rules:
- Optional fallback map (can be empty).
- Checked top-to-bottom.
- All tokens in `match` must be present (AND logic).
- First match wins.
- `profile_id` must be a valid Sonarr quality profile id.

`sonarr.mapping.language_profile_map` rules:
- Optional fallback map (can be empty).
- Checked top-to-bottom.
- All tokens in `match` must be present (AND logic).
- First match wins.
- `profile_id` must be a valid Sonarr language profile id.

`radarr.mapping.quality_map.target_id` uses Radarr quality definitions:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualitydefinition
```

`radarr.auto_add_quality_profile_id` uses Radarr quality profiles:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualityprofile
```

`radarr.mapping.custom_format_map.format_id` uses Radarr custom formats:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/customformat
```

`sonarr.mapping.quality_profile_map.profile_id` uses Sonarr quality profiles:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://sonarr:8989/api/v3/qualityprofile
```

`sonarr.mapping.language_profile_map.profile_id` uses Sonarr language profiles:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://sonarr:8989/api/v3/languageprofile
```

## Analysis

`analysis.use_nfo`:
- Enables NFO token extraction during quality mapping.

`analysis.use_media_probe`:
- Enables ffprobe token extraction.
- Extracts codec/channels and audio language tags (`stream_tags=language`) when present.

`analysis.media_probe_bin`:
- Probe executable name/path (default `ffprobe`).

Quality matching order:
1. Filename/folder text
2. NFO text (if enabled)
3. Probe tokens (if enabled)

Audio language token notes:
- Common language tags are normalized to spoken tokens plus `lang-xx` tokens (for example `deu/ger/de` -> `german` + `lang-de`, `eng/en` -> `english` + `lang-en`, `fra` -> `french`, `spa` -> `spanish`).
- Compact combined tags from metadata sources (for example `gereng`) are split when possible and mapped to multiple languages.
- `multi-language` and `dual-language` tokens are emitted when at least two recognized languages are detected.

## Ingest

`ingest.*` options are currently retained for compatibility and config stability.

- They are not used by the active projection-first reconcile pipeline.
- Keep existing values to preserve backward-compatible config files.

## Cleanup

`cleanup.remove_orphaned_links`:
- Removes links whose source no longer exists.

`cleanup.sonarr_action_on_missing`:
- Controls Sonarr behavior when source disappears.
- `none`: leave Sonarr state untouched (recommended for transient disconnects/renames).
- `unmonitor`: unmonitor after `cleanup.missing_grace_seconds`.
- `delete`: delete from Sonarr after `cleanup.missing_grace_seconds`.

`cleanup.missing_grace_seconds`:
- Delay before `unmonitor` or `delete` is applied.
- Helps avoid false actions during temporary storage/network outages.
- Missing-item actions are applied in both full and incremental reconciles.

## Runtime

`runtime.debounce_seconds`:
- Debounce window for filesystem events.
- Filesystem events trigger incremental reconcile for configured managed/library roots.

`runtime.maintenance_interval_minutes`:
- Periodic full reconcile interval.
- Set `0` to disable periodic maintenance (event-driven only after startup).

`runtime.arr_root_poll_interval_minutes`:
- Interval for polling Radarr/Sonarr root-folder catalogs.
- Triggers reconcile when configured roots become available later:
  - Radarr: configured `managed_root` paths in `paths.movie_root_mappings`
  - Sonarr: configured `nested_root` paths in `paths.root_mappings`
- LibrariArr triggers a reconcile automatically (without restart or filesystem touch).
- Set `0` to disable this poller.

`runtime.scan_video_extensions`:
- Extensions that mark a directory as a media folder.
- Leading dots are optional (`mkv` and `.mkv` are treated the same).
- Default includes: `.mkv`, `.mp4`, `.avi`, `.m2ts`, `.mov`, `.wmv`, `.ts`, `.m4v`, `.mpg`, `.mpeg`.

## Env Overrides

Only these app-level runtime env overrides are supported:
- `LIBRARIARR_RADARR_URL`
- `LIBRARIARR_RADARR_API_KEY`
- `LIBRARIARR_SONARR_URL`
- `LIBRARIARR_SONARR_API_KEY`

All other app behavior should be configured in `config.yaml`.
