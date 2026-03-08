# LibrariArr

LibrariArr lets you keep your real movie files in nested folders while presenting Radarr with a flat library root.

It does this by creating symlinks in a shadow folder and, when enabled, updating matching movies in Radarr to point at those symlinks.

## Why You Would Use It

Some people organize files like this:

```text
/data/movies/
  age_12/Studio/Foo (2020)/Foo.2020.1080p.x265.mkv
  age_16/Other/Bar (2011)/Bar.2011.2160p.REMUX.mkv
```

Radarr expects a flatter root layout. LibrariArr builds that view for Radarr:

```text
/data/radarr_library/
  Foo (2020) -> /data/movies/age_12/Studio/Foo (2020)
  Bar (2011) -> /data/movies/age_16/Other/Bar (2011)
```

If two folders would create the same link name, LibrariArr auto-qualifies the name to keep links unique.

If you want age-specific Radarr roots, use `paths.root_mappings` so each source root writes to its own shadow root.

## What It Actually Does

1. Scans configured nested roots for movie folders (folder containing a video file).
2. Creates missing symlinks in the shadow root.
3. If Radarr sync is enabled, matches movies by `Title (Year)` first, then title-only fallback.
4. Updates Radarr movie path to the symlink path.
5. Attempts quality mapping based on configured rules.
6. Cleans up orphaned symlinks and can unmonitor or delete from Radarr on missing source folders.
7. Runs an initial reconcile at startup, then continues via filesystem events and periodic maintenance.

## Docker Compose Setup

1. Create local config files:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

2. Edit `config.yaml` and `.env` for your paths and Radarr API key.

3. Make sure host path mappings in `.env` exist and are writable:

```dotenv
MOVIES_HOST_PATH=/data/movies
RADARR_LIBRARY_HOST_PATH=/data/radarr_library
```

4. Set container user mapping in `.env` to avoid ownership issues on Linux:

```dotenv
PUID=1000
PGID=1000
```

5. Start LibrariArr:

```bash
./run.sh up
```

6. Check logs:

```bash
./run.sh logs
```

7. Stop when needed:

```bash
./run.sh down
```

## Radarr Integration Requirements

1. `radarr` and `librariarr` must see the same shadow-root path in-container.
2. Add `/data/radarr_library` as a Radarr root folder.
3. Use a valid Radarr API key.

If `radarr.sync_enabled` (or `LIBRARIARR_RADARR_SYNC_ENABLED`) is `false`, LibrariArr still manages symlinks but does not call Radarr APIs.

Per-root shadow mapping example (age buckets):

```yaml
paths:
  root_mappings:
    - nested_root: /data/movies/age_06
      shadow_root: /data/radarr_library/age_06
    - nested_root: /data/movies/age_12
      shadow_root: /data/radarr_library/age_12
    - nested_root: /data/movies/age_16
      shadow_root: /data/radarr_library/age_16
```

With this, links are not merged into one folder. Each age root is reconciled into its mapped shadow root.

## Embed Into Existing *arr Stack

If you already run `radarr` in your own compose stack, add `librariarr` as another service and keep path variables consistent with your existing naming pattern.

Example with `CONFIG_ROOT` style variables:

```yaml
services:
  radarr:
    image: lscr.io/linuxserver/radarr:latest
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
      - TZ=${TZ}
    volumes:
      - ${CONFIG_ROOT}/radarr:/config
      - ${MOVIES_DIR}:/data/movies
      - ${RADARR_LIBRARY_DIR}:/data/radarr_library

  librariarr:
    image: ghcr.io/vtietz/librariarr:latest
    container_name: librariarr
    environment:
      - PUID=${PUID}
      - PGID=${PGID}
      - TZ=${TZ}
      - LIBRARIARR_RADARR_URL=http://radarr:7878
      - LIBRARIARR_RADARR_API_KEY=${RADARR_API_KEY}
      - LIBRARIARR_RADARR_SYNC_ENABLED=true
      - LIBRARIARR_NESTED_ROOTS=/data/movies/age_06,/data/movies/age_12,/data/movies/age_16
      - LIBRARIARR_SHADOW_ROOT=/data/radarr_library
    volumes:
      - ${CONFIG_ROOT}/librariarr/config.yaml:/config/config.yaml:ro
      - ${MOVIES_DIR}:/data/movies
      - ${RADARR_LIBRARY_DIR}:/data/radarr_library
    command: ["--config", "/config/config.yaml", "--log-level", "INFO"]
    restart: unless-stopped
    depends_on:
      - radarr
```

Important:

1. In Radarr, set root folder to `/data/radarr_library`.
2. Keep container paths identical across both services.
3. `LIBRARIARR_RADARR_URL` should use the Radarr service name (`http://radarr:7878`) when they share a compose network.
4. For age-based roots, add each mapped path as a Radarr root folder (`/data/radarr_library/age_06`, etc.).

What it means to merge with your existing compose file:

1. Do not replace your stack.
2. Add one new service: `librariarr`.
3. Add one new shared volume mapping to `radarr` if missing: `${RADARR_LIBRARY_DIR}:/data/radarr_library`.
4. Add `RADARR_LIBRARY_DIR` and any missing LibrariArr env vars to your `.env`.
5. Set Radarr root folder to `/data/radarr_library` in the Radarr UI.

For age-based roots, add all mapped roots in Radarr instead of only one.

## Configuration Reference

`config.yaml.example` is the baseline. Values below show effective defaults and env overrides.

| Option | Default | Env Override |
|---|---|---|
| `paths.nested_roots` | Required in config example | `LIBRARIARR_NESTED_ROOTS` (comma-separated) |
| `paths.root_mappings` | `[]` | None |
| `radarr.url` | Required in config example | `LIBRARIARR_RADARR_URL` |
| `radarr.api_key` | Required in config example | `LIBRARIARR_RADARR_API_KEY` |
| `radarr.shadow_root` | `/data/radarr_library` | `LIBRARIARR_SHADOW_ROOT` |
| `radarr.sync_enabled` | `true` | `LIBRARIARR_RADARR_SYNC_ENABLED` |
| `quality_map` | `[]` | None |
| `cleanup.remove_orphaned_links` | `true` | None |
| `cleanup.unmonitor_on_delete` | `true` | None |
| `cleanup.delete_from_radarr_on_missing` | `false` | `LIBRARIARR_DELETE_FROM_RADARR_ON_MISSING` |
| `runtime.debounce_seconds` | `8` | None |
| `runtime.maintenance_interval_minutes` | `1440` | None |
| `runtime.scan_video_extensions` | `['.mkv','.mp4','.avi','.m2ts','.mov','.wmv','.ts']` | None |
| `analysis.use_nfo` | `false` | `LIBRARIARR_USE_NFO_ANALYSIS` |
| `analysis.use_media_probe` | `false` | `LIBRARIARR_USE_MEDIA_PROBE` |
| `analysis.media_probe_bin` | `ffprobe` | `LIBRARIARR_MEDIA_PROBE_BIN` |

Quality mapping behavior:

1. Rules are evaluated in order.
2. Every token in `match` must be present (AND match, case-insensitive).
3. If no rule matches, quality falls back to Radarr quality id `4`.
4. Optional analyzers (`nfo`, `media_probe`) are only used when enabled.
5. Matching order is: filename/folder text, then NFO text, then media probe tokens.

How to find `target_id` and profile names:

1. In Radarr UI: `Settings` -> `Profiles` -> `Quality`.
2. Or query Radarr API and read `id` + `name` values:

```bash
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualityprofile
```

`media_probe` details:

1. Uses the most likely main video file in a movie folder (tries to avoid `sample` or extras files).
2. Extracts tokens from ffprobe for resolution and codec (`2160p`, `1080p`, `720p`, `x265`, `x264`, `hevc`, `h264`).
3. Also emits optional technical tokens: HDR transfer (`hdr10`, `hlg`), bitrate buckets (`medium-bitrate`, `high-bitrate`, `remux-bitrate`, `very-high-bitrate`), and audio hints (`truehd`, `dts`, `5.1`, `7.1`) when available.
4. Source labels like `hdtv`, `web`, and `bluray` are still most reliable from filename/NFO tags.

## Env vs Config: Which One Wins?

Precedence is:

1. Environment variable override.
2. `config.yaml` value.
3. Hardcoded default (if that field has one).

Root source precedence:

1. `paths.root_mappings` (if non-empty).
2. `paths.nested_roots` (or `LIBRARIARR_NESTED_ROOTS`) + one shared `radarr.shadow_root`.

Examples:

1. If `radarr.url` is set in `config.yaml`, but `LIBRARIARR_RADARR_URL` is also set, the env value is used.
2. If `cleanup.delete_from_radarr_on_missing` is `false` in `config.yaml`, but `LIBRARIARR_DELETE_FROM_RADARR_ON_MISSING=true`, deletion is enabled.
3. `cleanup.remove_orphaned_links` has no env override, so only `config.yaml` (or its default) controls it.

## Runtime Modes

Default mode runs continuously.

One-shot reconcile mode:

Runs a single full sync pass (scan, link creation/update, optional Radarr updates, cleanup) and then exits.

```bash
./run.sh once
```

## Compose Files in This Repo

1. `docker-compose.yml`: normal runtime service.
2. `docker-compose.dev.yml`: development container and tooling.
3. `docker-compose.e2e.yml`: Radarr integration end-to-end tests.
4. `docker-compose.fs-e2e.yml`: filesystem-focused end-to-end tests.

## Wrapper Script Hint

If you prefer shortcuts, this repo includes wrappers:

- Linux/macOS: `./run.sh`
- Windows: `run.bat`

Example:

```bash
./run.sh up
```

`run.sh` automatically detects whether your system supports `docker compose` (plugin) or legacy `docker-compose` and uses whichever is available.
