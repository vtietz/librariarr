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

Default naming behavior:

1. Symlink names are canonicalized to `Title (Year)` whenever the folder name contains a parseable year token.
2. Radarr sync mode does not control naming; it only controls whether Radarr APIs are called.
3. When a folder matches a Radarr movie, Radarr metadata is used as canonical source of title/year.
4. If no parseable year exists and no Radarr match exists, LibrariArr falls back to the source folder name.

## What It Actually Does

1. Scans configured nested roots for movie folders (folder containing a video file).
2. Creates missing symlinks in the shadow root.
3. Optional ingest mode (`ingest.enabled=true`) can move real folders created in shadow roots into configured nested roots, then replace the original shadow path with a symlink.
4. If Radarr sync is enabled, matches movies by `Title (Year)` first, then title-only fallback.
5. Updates Radarr movie path to the symlink path.
6. Attempts quality mapping based on configured rules.
7. Cleans up orphaned symlinks and can unmonitor or delete from Radarr on missing source folders.
8. Runs an initial reconcile at startup, then continues via filesystem events and periodic maintenance.

## Docker Compose Setup

1. Create local config files:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

2. Edit `config.yaml` for LibrariArr behavior and `.env` for Docker values (host paths/user IDs and optional Radarr URL/API key overrides).

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
2. `radarr` and `librariarr` must see the same nested movie path(s) in-container (for example, `/data/movies`).
3. Symlink targets are absolute in-container paths; Radarr must be able to resolve those exact paths.
4. Add `/data/radarr_library` as a Radarr root folder.
5. Use a valid Radarr API key.

Common pitfall:

1. LibrariArr creates links like `/data/flat/Foo (2020) -> /data/movies/...`.
2. Radarr maps `/data/movies` to a different host source than LibrariArr.
3. Radarr can see the link itself, but the target folder is missing in Radarr's container view.
4. Result: scans/imports look empty even though links exist.

How to retrieve Radarr API key:

1. In Radarr UI: `Settings` -> `General` -> `Security` -> `API Key` (enable `Show Advanced` if needed).
2. Or from container config:

```bash
docker-compose exec radarr sh -lc "grep -oPm1 '(?<=<ApiKey>)[^<]+' /config/config.xml"
```

If `radarr.sync_enabled` is `false`, LibrariArr still manages symlinks but does not call Radarr APIs.

If `radarr.sync_enabled` is `true` and path mapping is wrong:

1. Radarr can reject path updates when the target path is invalid for its container view or outside configured Radarr root folders.
2. LibrariArr logs the API failure and retries on the next reconcile cycle.
3. Fix by aligning container paths (`radarr` and `librariarr` must mount identical in-container roots) and adding the mapped shadow root(s) in Radarr (`Settings` -> `Media Management` -> `Root Folders`).

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

Version/cut note:

1. Radarr treats one movie as one path entry.
2. Multiple cuts/editions of the same title/year are not modeled as separate managed paths by default.
3. If duplicates collide, LibrariArr keeps links unique with suffixes, but Radarr will still track one active path for that movie.

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
      - LIBRARIARR_RADARR_URL=${LIBRARIARR_RADARR_URL:-http://radarr:7878}
      - LIBRARIARR_RADARR_API_KEY=${LIBRARIARR_RADARR_API_KEY}
    volumes:
      - ${CONFIG_ROOT}/librariarr:/config:ro
      - ${MOVIES_DIR}:/data/movies
      - ${RADARR_LIBRARY_DIR}:/data/radarr_library
    command: ["--config", "/config/config.yaml", "--log-level", "INFO"]
    restart: unless-stopped
    depends_on:
      - radarr
```

Config path gotcha (common in custom stacks):

1. The image default is `--config /config/config.yaml`.
2. If you mount to a different in-container path (for example `/app/config.yaml`), you must also override command to match that path.
3. Recommended mapping with `CONFIG_ROOT` style vars is `${CONFIG_ROOT}/librariarr:/config:ro` (directory mount).
4. Single-file bind is still valid if preferred: `${CONFIG_ROOT}/librariarr/config.yaml:/config/config.yaml:ro`.

Single-file bind variant:

```yaml
librariarr:
  volumes:
    - ${CONFIG_ROOT}/librariarr/config.yaml:/config/config.yaml:ro
  command: ["--config", "/config/config.yaml", "--log-level", "INFO"]
```

Important:

1. In Radarr, set root folder to `/data/radarr_library`.
2. Keep container paths identical across both services.
3. Set `LIBRARIARR_RADARR_URL=http://radarr:7878` in `.env` (or set `radarr.url` in config if you prefer file-only).
4. For age-based roots, add each mapped path as a Radarr root folder (`/data/radarr_library/age_06`, etc.).

Concrete custom-path example (`/data/flat` as shadow root):

```yaml
services:
  radarr:
    volumes:
      - ${MOVIES_DIR}:/data/movies
      - ${RADARR_FLAT_DIR}:/data/flat

  librariarr:
    volumes:
      - ${MOVIES_DIR}:/data/movies
      - ${RADARR_FLAT_DIR}:/data/flat
```

Matching `config.yaml` excerpt:

```yaml
paths:
  nested_roots:
    - /data/movies/FSK06 Kinder

radarr:
  shadow_root: /data/flat
```

Do not map `/data/movies` differently between Radarr and LibrariArr.

What it means to merge with your existing compose file:

1. Do not replace your stack.
2. Add one new service: `librariarr`.
3. Add one new shared volume mapping to `radarr` if missing: `${RADARR_LIBRARY_DIR}:/data/radarr_library`.
4. Add `RADARR_LIBRARY_DIR` to `.env` if missing.
5. Configure LibrariArr in `${CONFIG_ROOT}/librariarr/config.yaml`; optionally set `LIBRARIARR_RADARR_URL` and `LIBRARIARR_RADARR_API_KEY` in `.env`.
6. Set Radarr root folder to `/data/radarr_library` in the Radarr UI.

For age-based roots, add all mapped roots in Radarr instead of only one.

## Configuration Reference

`config.yaml.example` is the baseline.

| Option | Default |
|---|---|
| `paths.nested_roots` | Required in config example |
| `paths.root_mappings` | `[]` |
| `radarr.url` | Required in config example |
| `radarr.api_key` | Required in config example |
| `radarr.shadow_root` | `/data/radarr_library` |
| `radarr.sync_enabled` | `true` |
| `ingest.enabled` | `false` |
| `ingest.min_age_seconds` | `30` |
| `ingest.collision_policy` | `qualify` |
| `ingest.quarantine_root` | `""` (disabled) |
| `quality_map` | `[]` |
| `cleanup.remove_orphaned_links` | `true` |
| `cleanup.unmonitor_on_delete` | `true` |
| `cleanup.delete_from_radarr_on_missing` | `false` |
| `runtime.debounce_seconds` | `8` |
| `runtime.maintenance_interval_minutes` | `1440` (`0` disables periodic maintenance scans) |
| `runtime.scan_video_extensions` | `['.mkv','.mp4','.avi','.m2ts','.mov','.wmv','.ts']` |
| `analysis.use_nfo` | `false` |
| `analysis.use_media_probe` | `false` |
| `analysis.media_probe_bin` | `ffprobe` |

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
curl -s -H "X-Api-Key: <API_KEY>" http://radarr:7878/api/v3/qualitydefinition
```

`media_probe` details:

1. Uses the most likely main video file in a movie folder (tries to avoid `sample` or extras files).
2. Extracts tokens from ffprobe for resolution and codec (`2160p`, `1080p`, `720p`, `x265`, `x264`, `hevc`, `h264`).
3. Also emits optional technical tokens: HDR transfer (`hdr10`, `hlg`), bitrate buckets (`medium-bitrate`, `high-bitrate`, `remux-bitrate`, `very-high-bitrate`), and audio hints (`truehd`, `dts`, `5.1`, `7.1`) when available.
4. Source labels like `hdtv`, `web`, and `bluray` are still most reliable from filename/NFO tags.

## Config Source

LibrariArr uses `config.yaml` for almost all app settings.

1. App behavior is read from `config.yaml`.
2. `.env` is used for Docker Compose interpolation (host paths, IDs, ports, optional log level).
3. Only two runtime env overrides are supported by the app: `LIBRARIARR_RADARR_URL` and `LIBRARIARR_RADARR_API_KEY`.
4. All other `LIBRARIARR_*` app settings must be in `config.yaml`.

Root source precedence:

1. `paths.root_mappings` (if non-empty).
2. `paths.nested_roots` + one shared `radarr.shadow_root`.

## Optional Ingest Mode

By default, LibrariArr is one-way: nested roots are scanned and projected into shadow roots as symlinks.

If you enable ingest (`ingest.enabled: true`), LibrariArr also handles real directories that appear in shadow roots:

1. Detects non-symlink movie directories in configured shadow roots.
2. Waits for quiescence (`ingest.min_age_seconds`) to avoid moving in-progress writes.
3. Requires a 1:1 mapping between each shadow root and nested root.
4. Moves the folder into nested storage.
5. Recreates the original shadow path as a symlink to the moved folder.

This keeps Radarr-visible paths stable while preserving nested roots as the physical source of truth.

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
