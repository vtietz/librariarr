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

quality_map:
  - match: ["1080p", "bluray", "x265"]
    target_id: 7
```

## Paths

`paths.root_mappings`:
- Recommended mode.
- Each nested source root maps to one shadow root.
- Avoids ambiguity and works best with ingest.

`paths.nested_roots`:
- Legacy mode.
- All nested roots share one `radarr.shadow_root`.
- Use only if you intentionally want one merged shadow library.

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

`radarr.auto_add_quality_profile_id`:
- Optional fixed quality profile id for auto-add.
- If omitted, LibrariArr tries to map from `quality_map`/analysis to a profile.
- If no mapping is possible, falls back to the lowest available profile id.

`radarr.auto_add_search_on_add`:
- If true, Radarr starts indexer search immediately after add.
- Keep false if you only want registration/path import behavior.

`radarr.auto_add_monitored`:
- Initial Radarr monitored flag for newly auto-added entries.

`radarr.shadow_root`:
- Legacy-only shared shadow root.
- Used only with `paths.nested_roots`.

## Quality Mapping

`quality_map` rules:
- Checked top-to-bottom.
- All tokens in `match` must be present (AND logic).
- First match wins.
- If no match, fallback quality definition id is `4`.

`quality_map.target_id` uses Radarr quality definitions:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualitydefinition
```

`radarr.auto_add_quality_profile_id` uses Radarr quality profiles:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualityprofile
```

## Analysis

`analysis.use_nfo`:
- Enables NFO token extraction during quality mapping.

`analysis.use_media_probe`:
- Enables ffprobe token extraction.

`analysis.media_probe_bin`:
- Probe executable name/path (default `ffprobe`).

Quality matching order:
1. Filename/folder text
2. NFO text (if enabled)
3. Probe tokens (if enabled)

## Ingest

`ingest.enabled`:
- Enables ingest of real folders created in shadow roots.

`ingest.min_age_seconds`:
- Folder must be unchanged for at least this long before ingest.

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

`runtime.scan_video_extensions`:
- Extensions that mark a directory as a movie folder.

## Env Overrides

Only these app-level runtime env overrides are supported:
- `LIBRARIARR_RADARR_URL`
- `LIBRARIARR_RADARR_API_KEY`

All other app behavior should be configured in `config.yaml`.
