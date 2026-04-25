# LibrariArr

LibrariArr keeps real media folders in your preferred nested structure while continuously syncing library views for Radarr and Sonarr.

It solves the path drift problem between your filesystem and *arr apps by projecting managed
media into curated library roots with hardlinks.

## What Problem It Solves

Many libraries are organized for humans (age buckets, studio folders, custom hierarchies), while Radarr and Sonarr work best with flat root folders.

Without synchronization, this causes:

- imports that fail because *arr paths no longer match real folders,
- stale entries after external renames or moves,
- extra manual path fixing in Radarr/Sonarr,
- brittle workflows when multiple tools touch the same files.

LibrariArr bridges that gap and keeps both sides aligned.

## Status

LibrariArr is a personal project built to scratch a real itch. It runs on an actual media library and is developed iteratively — which means it works, but it is not hardened software with enterprise guarantees.

**Use at your own risk.** Before pointing it at a library you care about, take a backup. Hardlinks are non-destructive by nature, but path updates and ingest moves are real filesystem operations. The authors make no warranty, express or implied.

A fair portion of this codebase was shaped through conversational AI collaboration — what some call vibe coding. The architecture was designed deliberately, the logic was reasoned through carefully, and the tests exist for a reason. But if something goes sideways in an unexpected corner case, that's between you and the universe.

## Core Features

- Continuous projection sync for Radarr and Sonarr using filesystem events plus scheduled maintenance reconciles.
- Startup Full Reconcile on every launch and on-demand via the admin UI to bring the library to a consistent state in one pass.
- Embedded web UI for visual config editing, mapping exploration, diagnostics, and dry-runs.
- Movie projection mappings (`paths.movie_root_mappings`) and series projection mappings (`paths.series_root_mappings`).
- Hardlink projection for managed video files plus allowlisted extras.
- Optional webhook-scoped projection via `POST /api/hooks/radarr` and `POST /api/hooks/sonarr`.
- Idempotent reconcile behavior with relink-on-replace and unknown-file preservation.

## Sync Architecture

```mermaid
flowchart LR
  A[Nested media folders under /data] --> B[LibrariArr discovery + reconcile]
  B --> C[Hardlink projection into /data/movies and /data/sonarr_library]
  B --> D[Radarr movie inventory]
  B --> E[Sonarr series inventory]
```

## How It Works

Example managed-to-projected movie layout (path-preserving mode):

This example shows the same files in two places:
- Managed source tree (where you organize media).
- Projected Radarr library tree (hardlink view that Radarr reads).

In this example, projection preserves relative subfolders because it assumes:
- `radarr.projection.movie_folder_name_source=managed`
- a broad mapping like `/data/movies -> /data/radarr_library`

If you want a flatter projected layout, use narrower root mappings (for example one mapping per age bucket) and/or set `movie_folder_name_source` to Arr title-based naming.

```text
[MAPPING USED IN THIS EXAMPLE]
/data/movies  ->  /data/radarr_library

[MANAGED SOURCE]
/data/movies/
  age_12/Studio/Foo (2020)/Foo.2020.1080p.x265.mkv
  age_16/Other/Bar (2011)/Bar.2011.2160p.REMUX.mkv

[PROJECTED LIBRARY VIEW]
/data/radarr_library/
  age_12/Studio/Foo (2020)/Foo.2020.1080p.x265.mkv
  age_16/Other/Bar (2011)/Bar.2011.2160p.REMUX.mkv

NOTE: In path-preserving mode, the relative subpath (age_12/Studio/...) is intentionally the same.
Only the root changes from /data/movies to /data/radarr_library.

[FLATTER ALTERNATIVE EXAMPLE]
Mappings:
  /data/movies/age_12 -> /data/radarr_library/age_12
  /data/movies/age_16 -> /data/radarr_library/age_16

Projected:
  /data/radarr_library/age_12/Foo (2020)/Foo.2020.1080p.x265.mkv
  /data/radarr_library/age_16/Bar (2011)/Bar.2011.2160p.REMUX.mkv
```

The projected files are hardlinks to the managed files (same content, different path entry).

On reconcile, LibrariArr:

1. Reads Radarr movie inventory and Sonarr series inventory.
2. Resolves managed->library mappings.
3. Builds projection plans for managed video and allowlisted extras.
4. Applies hardlink projection idempotently into library roots.

## Common Sync Scenarios

### When Radarr/Sonarr downloads or imports media

- The download/import creates filesystem events under your nested roots.
- LibrariArr debounces bursts (`runtime.debounce_seconds`) and runs an incremental reconcile.
- Projection reuses existing hardlinks when unchanged and links new/replaced managed files.

### When you rename/move a movie or series folder manually

- Rename/move is detected via filesystem events and queued for incremental reconcile.
- Next reconcile projects from the Arr item path currently known to Radarr/Sonarr.
- Webhook queue scoping can speed up convergence to changed items.

### When you add files into an existing folder

- Events are detected and reconciled, but the folder identity often remains unchanged.
- You may still see a reconcile run in logs even if resulting projected-file changes are zero.

## Quick Start (Users: Docker Compose)

These steps are for regular Docker users (Docker CLI, Docker Desktop, or Portainer), not local repository development.

1. Copy defaults:

```bash
cp config.yaml.example config.yaml
cp .env.example .env
```

2. Set writable host paths in `.env` (single-root best practice):

```dotenv
MEDIA_ROOT=/volume2
PUID=1000
PGID=1000
```

Use one shared top-level mount (`MEDIA_ROOT`) across all *arr services and LibrariArr for reliable atomic moves and consistent path resolution.

3. Use the provided full-stack example compose file at the repository root:

```yaml
services:
  sabnzbd:
    image: lscr.io/linuxserver/sabnzbd:latest
    env_file: .env
    volumes:
      - ${CONFIG_ROOT}/sabnzbd:/config
      - ${MEDIA_ROOT}:/data

  radarr:
    image: lscr.io/linuxserver/radarr:latest
    env_file: .env
    volumes:
      - ${CONFIG_ROOT}/radarr:/config
      - ${MEDIA_ROOT}:/data

  sonarr:
    image: lscr.io/linuxserver/sonarr:latest
    env_file: .env
    volumes:
      - ${CONFIG_ROOT}/sonarr:/config
      - ${MEDIA_ROOT}:/data

  librariarr:
    image: ghcr.io/vtietz/librariarr:latest
    env_file: .env
    volumes:
      - ${CONFIG_ROOT}/librariarr:/config
      - ${MEDIA_ROOT}:/data
    ports:
      - "8787:8787"
    command: ["--config", "/config/config.yaml", "--log-level", "INFO", "--web"]
```

4. Start and verify:

```bash
docker compose -f docker-compose.full-stack.example.yml up -d
docker compose -f docker-compose.full-stack.example.yml logs -f librariarr
```

Then open `http://localhost:8787` for the LibrariArr GUI.

### Linux note: inotify watch limits

If logs show `OSError: [Errno 28] inotify watch limit reached`, increase host
inotify limits (run on the Docker host, not inside the container):

```bash
sudo sysctl -w fs.inotify.max_user_watches=524288
sudo sysctl -w fs.inotify.max_user_instances=1024
```

Persist after reboot:

```bash
printf 'fs.inotify.max_user_watches=524288\nfs.inotify.max_user_instances=1024\n' | \
  sudo tee /etc/sysctl.d/99-librariarr-inotify.conf
sudo sysctl --system
```

5. Stop when needed:

```bash
docker compose -f docker-compose.full-stack.example.yml down
```

## Minimal Config Example

```yaml
paths:
  movie_root_mappings:
    - managed_root: "/data/radarr_library/age_12"
      library_root: "/data/movies/age_12"
  series_root_mappings:
    - nested_root: "/data/series/age_12"
      shadow_root: "/data/sonarr_library/age_12"

radarr:
  enabled: true
  url: "http://radarr:7878"
  api_key: "YOUR_API_KEY"
  sync_enabled: true

sonarr:
  enabled: false
  url: "http://sonarr:8989"
  api_key: "YOUR_API_KEY"
  sync_enabled: true
```

## Integration Checklist

- Radarr/Sonarr and LibrariArr must all mount the same top-level media root to `/data`.
- Keep nested and shadow folders under that shared root (for example `/data/movies`, `/data/radarr_library`, `/data/sonarr_library`).
- Add mapped shadow roots as root folders in Radarr/Sonarr.
- Keep `radarr.enabled=true` for movie processing, `sonarr.enabled=true` for series processing.
- Use `*.sync_enabled=false` to disable Arr API projection for that service.
- If API sync is enabled and updates fail, check path parity across containers first.

## More Details

- Full option reference: [docs/configuration.md](docs/configuration.md)
- Workflow/reference behavior guide: [docs/workflows.md](docs/workflows.md)
- Example baseline: [config.yaml.example](config.yaml.example)
- Main compose file: [docker-compose.yml](docker-compose.yml)
- Dev compose file: [docker-compose.dev.yml](docker-compose.dev.yml)
- Full stack compose example (Sabnzbd/Radarr/Sonarr/Prowlarr/LibrariArr/Mediathekarr, documentation-only): [docker-compose.full-stack.example.yml](docker-compose.full-stack.example.yml)
- Wrapper help script (contributors/local repo dev): [run.sh](run.sh)

## Contributor Commands (Repo Checkout)

These `run.sh` wrappers are for contributors and local repository development.

- `./run.sh once` for single reconcile.
- `./run.sh test` for unit/integration tests (non-e2e).
- `./run.sh e2e` for Arr end-to-end tests (Radarr + Sonarr).
- `./run.sh fs-e2e` for filesystem-focused end-to-end tests.
- `./run.sh quality` for lint/format/complexity checks.

### Dev GUI + Local Arr Stack

Prerequisites:

- Docker with Compose support (`docker compose` or `docker-compose`)
- Writable host media root (`MEDIA_ROOT`) for local folder/bootstrap operations
- A repo-local `config.yaml` file (auto-created by wrappers when missing)

- Create env file: `cp .env.dev.example .env`
- Start full dev stack: `./run.sh dev-up`
- One-time/bootstrap only (optional): `./run.sh dev-bootstrap`
- Seed sample folders/files into configured nested roots (optional): `./run.sh dev-seed`
- GUI API: `http://localhost:8787`
- Vite dev UI: `http://localhost:5173`
- Radarr dev instance: `http://localhost:17878`
- Sonarr dev instance: `http://localhost:18989`
- Tail logs: `./run.sh dev-logs`
- Stop everything: `./run.sh dev-down`

Ports and internal dev URLs can be adjusted in `.env` via `LIBRARIARR_WEB_PORT`,
`LIBRARIARR_DEV_RADARR_URL`, `LIBRARIARR_DEV_SONARR_URL`,
`DEV_HOST_PORT_RADARR`, and `DEV_HOST_PORT_SONARR`.

By default, `dev-up` creates `.env` from `.env.dev.example` when missing and runs
`dev-bootstrap` automatically (`LIBRARIARR_DEV_BOOTSTRAP=0` disables auto-bootstrap).
The bootstrap syncs Arr API keys/URLs into `config.yaml` and `.env`, tries to disable
Arr auth/HTTPS for local dev, and ensures root folders exist.
Before startup, `dev-up` also pre-creates `movies`, `series`, `radarr_library`, and
`sonarr_library` under `MEDIA_ROOT` when the host path is writable.
If host-side creation is blocked by ownership/permissions, `dev-bootstrap` runs an
in-container repair step that creates/chowns mapped `/data` paths before Arr root
folder registration.
