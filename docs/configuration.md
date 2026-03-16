# Configuration Guide

Use `config.yaml.example` as your starting point.

This page is the detailed reference for all `config.yaml` options.

For end-to-end lifecycle behavior examples, see `docs/workflows.md`.

## Quick Start

Recommended baseline:

```yaml
paths:
  root_mappings:
    - nested_root: "/data/movies/age_06"
      shadow_root: "/data/radarr_library/age_06"
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
  auto_add_unmatched: false
  auto_add_search_on_add: false
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
- `radarr.enabled=false` disables movie-folder discovery and Radarr integration entirely (useful for Sonarr-only setups).
- `sonarr.enabled=true` enables series-folder discovery and Sonarr path synchronization.
- `sonarr.auto_add_unmatched=true` enables Sonarr auto-creation for unmatched series folders.
- `radarr.refresh_debounce_seconds=15` helps avoid duplicate `RefreshMovie` bursts for the same movie during noisy event windows; set `0` to disable.
- `sonarr.refresh_debounce_seconds=15` helps avoid duplicate `RefreshSeries` bursts during noisy rename windows.
- Keep `radarr.auto_add_search_on_add=false` unless you explicitly want immediate indexer searches after auto-add.
- Leave `radarr.auto_add_quality_profile_id` unset to use automatic profile mapping. Set it only when you want strict, fixed-profile behavior.
- Example ingest defaults (`enabled=true`, `min_age_seconds=300`) favor safe move-back behavior and reduce the risk of ingesting partially written folders.
- `ingest.collision_policy=qualify` keeps ingest moving by appending a deterministic suffix like `[ingest-2]`; `skip` leaves the source directory in the shadow root.
- `radarr.mapping.custom_format_map` is optional and useful when Radarr parse cannot infer enough custom-format signal from release title alone.
- Keep `radarr.mapping.quality_map` short if you use it as fallback; start with resolution and codec signals.
- Enable `analysis.use_media_probe=true` for more reliable quality detection when filenames are inconsistent.
- On startup preflight, LibrariArr logs configured Radarr/Sonarr mapping ids and catalogs (`id:name`) to make id verification easier.
- Prefer `cleanup.radarr_action_on_missing=none` with a non-zero `cleanup.missing_grace_seconds` when libraries may be temporarily unavailable.
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

`paths.root_mappings`:
- Each nested source root maps to one shadow root.
- Avoids ambiguity and works best with ingest.
- Managed link names are derived from discovered folder names.
- Arr metadata titles do not control shadow link names.

`paths.exclude_paths`:
- Optional list of glob-style ignore patterns applied during movie/series discovery.
- Patterns are evaluated relative to each `nested_root` (gitignore-style intent).
- Useful for skipping transient/trash trees such as `.deletedByTMM/`.
- Supports `*` and `**` globs, and comments/blank entries are ignored.

## Radarr

`radarr.enabled`:
- Enables movie-folder discovery and Radarr integration flow.
- If false, movie folders are ignored.

`radarr.url`:
- Radarr base URL (for example `http://radarr:7878`).

`radarr.api_key`:
- Radarr API key.

`radarr.sync_enabled`:
- Enables all Radarr API interactions.
- If false while `radarr.enabled=true`, LibrariArr manages movie symlinks only.

`radarr.refresh_debounce_seconds`:
- Debounce window for `RefreshMovie` commands per movie id.
- Default is `15` seconds.
- Set `0` to disable debounce.

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
- Enables Sonarr-series discovery and integration flow.

`sonarr.url`:
- Sonarr base URL (for example `http://sonarr:8989`).

`sonarr.api_key`:
- Sonarr API key.

`sonarr.sync_enabled`:
- Enables Sonarr API interactions.
- If false while `sonarr.enabled=true`, LibrariArr manages series symlinks only.

`sonarr.refresh_debounce_seconds`:
- Debounce window for `RefreshSeries` commands per series id.
- Default is `15` seconds.
- Set `0` to disable debounce.

`sonarr.auto_add_unmatched`:
- If true, unmatched series folders can be auto-added to Sonarr.
- Auto-add still converges to folder-derived managed link paths.

`sonarr.auto_add_quality_profile_id`:
- Optional fixed quality profile id for Sonarr auto-add.
- If omitted, LibrariArr checks `sonarr.mapping.quality_profile_map` first, then falls back to the lowest available Sonarr quality profile id.

`sonarr.auto_add_language_profile_id`:
- Optional fixed language profile id for Sonarr auto-add.
- If omitted, LibrariArr checks `sonarr.mapping.language_profile_map` first, then uses the lowest available Sonarr language profile id when available.

`sonarr.auto_add_search_on_add`:
- If true, Sonarr starts search immediately after add.

`sonarr.auto_add_monitored`:
- Initial Sonarr monitored flag for newly auto-added series.

`sonarr.auto_add_season_folder`:
- Sets Sonarr `seasonFolder` when auto-adding series.

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

`ingest.enabled`:
- Enables ingest of real folders created in shadow roots.

`ingest.min_age_seconds`:
- Folder must be unchanged for at least this long before ingest.
- When candidates are too fresh, LibrariArr logs a deferral line and schedules retry reconciles after debounce until ingest can proceed.

`ingest.collision_policy`:
- `qualify`: keeps ingesting with deterministic suffixes.
- `skip`: leaves source untouched if destination exists.

`ingest.quarantine_root`:
- Optional recovery location for failed ingest moves.

Note:
- Ingest requires a 1:1 shadow-to-nested mapping.

## Cleanup

`cleanup.remove_orphaned_links`:
- Removes links whose source no longer exists.

`cleanup.radarr_action_on_missing`:
- Controls Radarr behavior when source disappears.
- `none`: leave Radarr state untouched (recommended for transient disconnects/renames).
- `unmonitor`: unmonitor after `cleanup.missing_grace_seconds`.
- `delete`: delete from Radarr after `cleanup.missing_grace_seconds`.

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
- Shadow-root nested file events under real top-level directories trigger
  incremental reconcile.
- Nested events under existing top-level symlink entries are ignored.

`runtime.maintenance_interval_minutes`:
- Periodic full reconcile interval.
- Set `0` to disable periodic maintenance (event-driven only after startup).
- Ingest deferrals from `ingest.min_age_seconds` still trigger temporary retry reconciles so fresh folders are retried without requiring a new filesystem event.

`runtime.arr_root_poll_interval_minutes`:
- Interval for polling Radarr/Sonarr root-folder catalogs.
- When one of the configured `shadow_root` paths becomes available in Arr later,
  LibrariArr triggers a reconcile automatically (without restart or filesystem touch).
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
