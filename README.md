# LibrariArr

LibrariArr keeps a nested movie archive compatible with Radarr's flat root-folder model.

Wrapper hint: use `./run.sh <command>` (Linux/macOS) or `run.bat <command>` (Windows) for all common actions.

## What it does

- Watches nested source roots for file/folder changes.
- Ensures every detected movie folder has a symlink in a flat shadow root: `radarr_library`.
- Uses filename heuristics to map movie quality IDs.
- Updates Radarr movie path to the shadow symlink path.
- Removes orphaned symlinks and optionally unmonitors deleted movies.
- Runs startup bootstrap and periodic maintenance reconcile.

## Example layout

Nested source folders (real files):

```text
/data/movies/
  age_12/
    Blender/
      Big Buck Bunny (2008)/
        Big.Buck.Bunny.2008.1080p.x265.mkv
  age_16/
    OpenFilms/
      Sintel (2010)/
        Sintel.2010.2160p.REMUX.mkv
```

Flat shadow library (symlinks only):

```text
/data/radarr_library/
  Big Buck Bunny (2008)   -> /data/movies/age_12/Blender/Big Buck Bunny (2008)
  Sintel (2010)           -> /data/movies/age_16/OpenFilms/Sintel (2010)
```

If two nested folders produce the same movie folder name, LibrariArr keeps links unique with
a deterministic qualifier from source path, for example:

```text
Sintel (2010)--age_16-OpenFilms
```

## Simple defaults used

- Shadow root name: `/data/radarr_library`
- Matching: `Title (Year)` exact first, then title-only fallback
- Delete behavior: remove orphan link + unmonitor + refresh
- No auto-delete from Radarr DB
- Quality rules: case-insensitive, all listed keywords required (`AND`)
- Default quality fallback: `4` (`HDTV-1080p`)
- Startup behavior: full import/reconcile immediately
- Event debounce: `8s`
- Maintenance interval: every `1440` minutes

## Is it a CLI?

Yes. The service is started via a CLI entrypoint:

```bash
python -m librariarr.main --config config.yaml
```

Additional mode:

```bash
python -m librariarr.main --config config.yaml --once
```

`--once` runs one reconcile cycle and exits.

## Config: YAML or ENV?

Both are supported.

- Use `config.yaml` for stable project config (quality rules, cleanup behavior, runtime settings).
- Use environment variables for secrets and deployment-specific overrides (especially Radarr API key and paths).

Supported env overrides:

- `LIBRARIARR_RADARR_URL`
- `LIBRARIARR_RADARR_API_KEY`
- `LIBRARIARR_RADARR_SYNC_ENABLED` (`true`/`false`)
- `LIBRARIARR_DELETE_FROM_RADARR_ON_MISSING` (`true`/`false`, default `false`)
- `LIBRARIARR_USE_NFO_ANALYSIS` (`true`/`false`, default `false`)
- `LIBRARIARR_USE_MEDIA_PROBE` (`true`/`false`, default `false`)
- `LIBRARIARR_MEDIA_PROBE_BIN` (default `ffprobe`)
- `LIBRARIARR_SHADOW_ROOT`
- `LIBRARIARR_NESTED_ROOTS` (comma-separated)

Radarr API key:

1. Open Radarr Web UI.
2. Go to `Settings` -> `General` -> `Security`.
3. Copy the `API Key` value.
4. Set it in `.env` as `LIBRARIARR_RADARR_API_KEY=...` (preferred), or in `config.yaml` under `radarr.api_key`.

Two-step mode is supported:

- `sync_enabled: true`: symlinks + Radarr API updates
- `sync_enabled: false`: symlinks only (no Radarr API calls)

Optional quality analyzers (off by default):

- Filename heuristics are always used first.
- If no filename rule matches and `analysis.use_nfo: true`, LibrariArr scans `.nfo` text.
- If still no match and `analysis.use_media_probe: true`, LibrariArr probes the media stream
  (via `ffprobe` by default) to infer tokens like `2160p`/`1080p` and `x265`/`x264`.

Optional destructive behavior (off by default):

- `cleanup.delete_from_radarr_on_missing: true` deletes missing movies from the Radarr DB.
- If `false`, LibrariArr only unmonitors + refreshes (safer default).

## Docker-first setup (no Python on host)

1. Create config and env files:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
# edit config.yaml and .env
```

Permissions note (Linux/Unix):

- Set `PUID` and `PGID` in `.env` to match the user/group that owns your media folders.
- This ensures created symlinks and writes use expected ownership.
- You can check values with `id -u` and `id -g` on the host.

2. Start the service:

```bash
./run.sh up
```

3. Build dev dependencies once (for test/quality commands):

```bash
./run.sh install
```

4. View logs:

```bash
./run.sh logs
```

5. Run one-shot reconcile:

```bash
./run.sh once
```

6. Run tests:

```bash
./run.sh test
```

7. Run end-to-end filesystem tests:

```bash
./run.sh e2e
```

8. Run end-to-end tests against a live Radarr container:

```bash
./run.sh radarr-e2e
```

Optional: pin the Radarr test image for deterministic runs:

```bash
export RADARR_TEST_IMAGE=lscr.io/linuxserver/radarr:latest
./run.sh radarr-e2e
```

9. Run quality checks:

```bash
./run.sh quality
```

10. Auto-fix quality issues and re-check:

```bash
./run.sh quality-autofix
```

11. Stop:

```bash
./run.sh down
```

Windows users can use `run.bat` with the same commands as `run.sh`.
`install` is intended to be run once (or again only when dependencies change).

## Docker Compose

Compose files are split by intent:

- `docker-compose.yml`: production-style service (`librariarr`)
- `docker-compose.dev.yml`: development service with source mounted (`librariarr-dev`)
- `docker-compose.e2e.yml`: end-to-end filesystem test service (`librariarr-e2e`)
- `docker-compose.test.yml` (`--profile radarr-e2e`): live Radarr integration test services

Dev mode examples:

```bash
./run.sh dev-up
./run.sh dev-logs
./run.sh dev-shell
./run.sh dev-down
```

## *arr Stack Integration Example

LibrariArr fits well into a typical `*arr` stack. The key is that both `radarr` and
`librariarr` must see the same movie paths inside the containers.

Example service addition:

```yaml
  librariarr:
    image: ghcr.io/<owner>/<repo>:latest
    container_name: librariarr
    environment:
      - TZ=${TZ}
      - LIBRARIARR_RADARR_URL=http://radarr:7878
      - LIBRARIARR_RADARR_API_KEY=${RADARR_API_KEY}
      - LIBRARIARR_RADARR_SYNC_ENABLED=true
      - LIBRARIARR_NESTED_ROOTS=/data/movies/age_12,/data/movies/age_16
      - LIBRARIARR_SHADOW_ROOT=/data/radarr_library
    volumes:
      - ./librariarr/config.yaml:/config/config.yaml:ro
      - ${MOVIES_DIR}:/data/movies
      - ${RADARR_LIBRARY_DIR}:/data/radarr_library
    command: ["--config", "/config/config.yaml", "--log-level", "INFO"]
    restart: unless-stopped
    depends_on:
      - radarr
```

Radarr side requirement:

- Add the same shadow volume to `radarr`, for example:
  - `${RADARR_LIBRARY_DIR}:/data/radarr_library`
- In Radarr, use `/data/radarr_library` as the movie root folder.

If you want symlink-only mode (no API writes), set:

```yaml
LIBRARIARR_RADARR_SYNC_ENABLED=false
```

## Manual Docker commands (optional)

Build image:

```bash
docker build -t librariarr:alpha .
```

Run once:

```bash
docker run --rm \
  -v /path/to/config.yaml:/config/config.yaml:ro \
  -v /data/movies:/data/movies \
  -v /data/radarr_library:/data/radarr_library \
  librariarr:alpha --config /config/config.yaml --once
```

## Config keys

See `config.yaml.example`.

Key sections:

- `paths.nested_roots`: nested source roots
- `radarr.url`, `radarr.api_key`, `radarr.shadow_root`
- `radarr.sync_enabled`
- `quality_map`: ordered rules (`match` + `target_id`)
- `cleanup.remove_orphaned_links`, `cleanup.unmonitor_on_delete`
- `cleanup.delete_from_radarr_on_missing`
- `analysis.use_nfo`, `analysis.use_media_probe`, `analysis.media_probe_bin`
- `runtime.debounce_seconds`, `runtime.maintenance_interval_minutes`

## GitHub CI and Docker Publish

- CI workflow: `.github/workflows/ci.yml`
  - Runs `./run.sh test` and `./run.sh quality` on pushes and pull requests.
- Docker publish workflow: `.github/workflows/publish-docker.yml`
  - Builds and pushes image to `ghcr.io/<owner>/<repo>` after successful `CI` runs on `main` commits, and via manual trigger.
