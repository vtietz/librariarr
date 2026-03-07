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
    Bond/
      Dr. No (1962)/
        Dr.No.1962.1080p.x265.mkv
  age_16/
    SciFi/
      Dune (2021)/
        Dune.2021.2160p.REMUX.mkv
```

Flat shadow library (symlinks only):

```text
/data/radarr_library/
  Dr. No (1962)   -> /data/movies/age_12/Bond/Dr. No (1962)
  Dune (2021)     -> /data/movies/age_16/SciFi/Dune (2021)
```

If two nested folders produce the same movie folder name, LibrariArr keeps links unique with
a deterministic qualifier from source path, for example:

```text
Dr. No (1962)--age_16-Classics
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
- `LIBRARIARR_SHADOW_ROOT`
- `LIBRARIARR_NESTED_ROOTS` (comma-separated)

Two-step mode is supported:

- `sync_enabled: true`: symlinks + Radarr API updates
- `sync_enabled: false`: symlinks only (no Radarr API calls)

## Docker-first setup (no Python on host)

1. Create config and env files:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
# edit config.yaml and .env
```

2. Start the service:

```bash
./run.sh up
```

3. View logs:

```bash
./run.sh logs
```

4. Run one-shot reconcile:

```bash
./run.sh once
```

5. Run tests:

```bash
./run.sh test
```

6. Run quality checks:

```bash
./run.sh quality
```

7. Auto-fix quality issues and re-check:

```bash
./run.sh quality-autofix
```

8. Stop:

```bash
./run.sh down
```

Windows wrappers:

```bat
run.bat up
run.bat logs
run.bat once
run.bat test
run.bat quality
run.bat quality-autofix
run.bat down
```

## Docker Compose

Main file: `docker-compose.yml`

- `librariarr`: production-style service
- `librariarr-dev` (`--profile dev`): development service with source mounted

Dev mode examples:

```bash
./run.sh dev-up
./run.sh dev-logs
./run.sh dev-shell
./run.sh dev-down
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
- `runtime.debounce_seconds`, `runtime.maintenance_interval_minutes`

## GitHub CI and Docker Publish

- CI workflow: `.github/workflows/ci.yml`
  - Runs `./run.sh test` and `./run.sh quality` on pushes and pull requests.
- Docker publish workflow: `.github/workflows/publish-docker.yml`
  - Builds and pushes image to `ghcr.io/<owner>/<repo>` after successful `CI` runs on `main` commits, and via manual trigger.
