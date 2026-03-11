# Configuration Guide

Use `config.yaml.example` as your starting point.

This page is the detailed reference for all `config.yaml` options.

## Quick Start

Recommended baseline:

```yaml
paths:
  root_mappings:
    - nested_root: "/data/movies/age_06"
      shadow_root: "/data/radarr_library/age_06"

radarr:
  url: "http://radarr:7878"
  api_key: "YOUR_API_KEY"
  sync_enabled: true
  auto_add_unmatched: true
  auto_add_search_on_add: false

ingest:
  enabled: true
  min_age_seconds: 300
  collision_policy: "qualify"

analysis:
  use_nfo: false
  use_media_probe: true

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
```

## Example Notes

`config.yaml.example` is intentionally brief. Use this section for the longer rationale:

- `radarr.auto_add_unmatched=true` is enabled in the example for out-of-the-box automation. Disable it if source folder names are often temporary or incomplete.
- Keep `radarr.auto_add_search_on_add=false` unless you explicitly want immediate indexer searches after auto-add.
- Leave `radarr.auto_add_quality_profile_id` unset to use automatic profile mapping. Set it only when you want strict, fixed-profile behavior.
- Example ingest defaults (`enabled=true`, `min_age_seconds=300`) favor safe move-back behavior and reduce the risk of ingesting partially written folders.
- `ingest.collision_policy=qualify` keeps ingest moving by appending a deterministic suffix like `[ingest-2]`; `skip` leaves the source directory in the shadow root.
- `custom_format_map` is optional and useful when Radarr parse cannot infer enough custom-format signal from release title alone.
- Keep `quality_map` short if you use it as fallback; start with resolution and codec signals.
- Enable `analysis.use_media_probe=true` for more reliable quality detection when filenames are inconsistent.
- On startup preflight, LibrariArr logs configured `custom_format_map` ids and the Radarr custom format catalog (`id:name`) to make id verification easier.

## How It Fits Together

Configuration interaction for auto-add/profile behavior:

1. If `radarr.auto_add_quality_profile_id` is set, that fixed profile is always used.
2. If it is not set, LibrariArr first uses custom-format signal from Radarr parse and local `custom_format_map`.
3. If no custom-format signal is available, LibrariArr tries parse-derived quality-definition signal from Radarr (`quality`/`qualityDefinition`).
4. If there is still no parse quality signal (or it does not map), LibrariArr falls back to `quality_map`.
5. If neither mapping path yields a profile, LibrariArr falls back to the lowest available Radarr profile id.
5. `analysis.use_nfo` and `analysis.use_media_probe` feed token extraction for both `custom_format_map` and `quality_map` matching.
6. `quality_map` is optional and can be short (or empty) when you primarily rely on custom-format-based mapping.

Why Radarr parse is title-based:
- Radarr `/api/v3/parse` accepts a `title` parameter, so parse-based custom format detection is driven by folder/file title strings.
- LibrariArr tries multiple title candidates (folder name, video stem, video filename), not only one title string.
- Parse output can also include quality-definition signal, which LibrariArr can use as a fallback for profile mapping.
- Deeper local analysis (NFO + ffprobe + filename tokens) can still influence profile selection, but custom-format-based influence requires `custom_format_map` because token-level signals do not map to Radarr custom format IDs automatically.

## Paths

`paths.root_mappings`:
- Each nested source root maps to one shadow root.
- Avoids ambiguity and works best with ingest.

## Radarr

`radarr.url`:
- Radarr base URL (for example `http://radarr:7878`).

`radarr.api_key`:
- Radarr API key.

`radarr.sync_enabled`:
- Enables all Radarr API interactions.
- If false, LibrariArr manages filesystem links only.

`radarr.auto_add_unmatched`:
- If true, unmatched folders can be auto-added to Radarr.
- Recommended for normal automation.
- Disable if your source folder names are frequently temporary/incomplete.

`radarr.auto_add_quality_profile_id`:
- Optional fixed quality profile id for auto-add.
- If set, this profile id is always used for newly auto-added movies.
- If omitted, LibrariArr maps automatically using this workflow:
  1. Try Radarr parse (`/api/v3/parse`) on folder/file titles and collect matched `customFormats`.
  2. Add optional local `custom_format_map` matches from filename/folder text, optional NFO, and optional ffprobe tokens.
  3. Score Radarr profiles by `formatItems` scores and select the best profile.
  4. If there is still no custom-format signal, try parse-derived quality-definition fallback.
  5. If parse quality is unavailable or cannot be mapped, use `quality_map` fallback scoring (`target_id` against profile cutoffs/allowed qualities).
  6. If no profile can be mapped from either signal, fall back to the lowest available profile id.
  7. If multiple profiles tie, prefer specific profile names over generic profiles (`Any`, `All`, `Default`).

`radarr.auto_add_search_on_add`:
- If true, Radarr starts indexer search immediately after add.
- Keep false if you only want registration/path import behavior.

`radarr.auto_add_monitored`:
- Initial Radarr monitored flag for newly auto-added entries.

## Quality Mapping

`quality_map` rules:
- Optional fallback map (can be empty).
- Checked top-to-bottom.
- All tokens in `match` must be present (AND logic).
- First match wins.
- If no match, fallback quality definition id is `4`.

`custom_format_map` rules:
- Optional and additive (all matching rules are collected).
- Uses the same token sources as quality mapping: filename/folder text, optional NFO, optional ffprobe tokens.
- `format_id` must be a valid Radarr custom format id.
- Helps preserve deeper local analysis signals (for example language/audio hints) when Radarr parse relies mostly on release title text.
- Without `custom_format_map`, deeper analytics still run for `quality_map`, but they do not create Radarr custom format IDs on their own.

`quality_map.target_id` uses Radarr quality definitions:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualitydefinition
```

`radarr.auto_add_quality_profile_id` uses Radarr quality profiles:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualityprofile
```

`custom_format_map.format_id` uses Radarr custom formats:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/customformat
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

`cleanup.unmonitor_on_delete`:
- Unmonitors Radarr entry when source disappears.

`cleanup.delete_from_radarr_on_missing`:
- Deletes Radarr entry instead of unmonitoring.

## Runtime

`runtime.debounce_seconds`:
- Debounce window for filesystem events.

`runtime.maintenance_interval_minutes`:
- Periodic full reconcile interval.
- Set `0` to disable periodic maintenance (event-driven only after startup).
- Ingest deferrals from `ingest.min_age_seconds` still trigger temporary retry reconciles so fresh folders are retried without requiring a new filesystem event.

`runtime.scan_video_extensions`:
- Extensions that mark a directory as a movie folder.

## Env Overrides

Only these app-level runtime env overrides are supported:
- `LIBRARIARR_RADARR_URL`
- `LIBRARIARR_RADARR_API_KEY`

All other app behavior should be configured in `config.yaml`.
