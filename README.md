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

- **Hardlink projection** (managed → library): projects video files and allowlisted extras from your curated folders into flat Arr-compatible library roots using hardlinks. Zero storage overhead.
- **Two-tier ingest** (library → managed): when Radarr imports a new movie, the folder is moved into your curated tree. When Radarr upgrades quality, file-level inode comparison detects new files and moves them in — no duplicates.
- **Auto-discovery**: scans managed roots for folders not yet in Radarr/Sonarr and auto-adds them with configurable quality profile mapping.
- **Webhook-scoped reconcile**: Radarr/Sonarr Connect webhooks trigger targeted per-movie/series reconcile within seconds instead of waiting for periodic scans.
- **Filesystem watchers + periodic reconcile**: filesystem events trigger debounced incremental reconcile; scheduled full reconcile catches any drift.
- **Idempotent and safe**: relink-on-replace for changed files, unknown user files in library roots are never touched.
- **Web UI**: dashboard with real-time status, config editor with validation, path mapping explorer, and log viewer.

## Sync Architecture

```mermaid
flowchart LR
  subgraph "Your curated folders"
    A[managed_root]
  end
  subgraph "LibrariArr"
    B[Reconcile]
  end
  subgraph "Arr library roots"
    C[library_root]
  end
  A -- "projection (hardlink)" --> B
  B --> C
  C -- "ingest (move)" --> B
  B --> A
  B <--> D[Radarr / Sonarr API]
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

1. **Ingests** new/upgraded files from library roots back into managed roots.
2. **Normalizes paths** so Radarr/Sonarr always point to library roots.
3. **Projects** managed video and allowlisted extras into library roots via hardlinks.
4. **Discovers** unmatched folders in managed roots and auto-adds them to Radarr/Sonarr.

## Common Sync Scenarios

### When Radarr downloads a new movie

- Radarr places the movie in the library root (its configured root folder).
- Webhook or filesystem event triggers reconcile.
- **Ingest** moves the folder from library root into your managed root.
- **Projection** hardlinks it back into the library root.
- Result: movie lives in your curated tree, Radarr sees it in the library root.

### When Radarr upgrades quality

- Radarr replaces the file in the library root with a better version.
- **File-level ingest** detects the new file (different inode) and moves it to managed root.
- **Projection** re-hardlinks the upgraded file back into the library root.
- Your curated folder now has the upgraded file, no duplicates.

### When you add a movie folder manually

- Drop a movie folder into your managed root.
- LibrariArr discovers it's not in Radarr and auto-adds it (if `auto_add_unmatched` is enabled).
- Projection hardlinks it into the library root so Radarr can see it.

### When you rename/move a movie folder

- Filesystem events trigger incremental reconcile.
- Projection updates to match the current managed folder state.

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
    - managed_root: "/data/movies/age_12"       # your curated folder
      library_root: "/data/radarr_library/age_12" # Radarr's root folder
  series_root_mappings:
    - nested_root: "/data/series/age_12"         # your curated folder
      shadow_root: "/data/sonarr_library/age_12" # Sonarr's root folder

radarr:
  enabled: true
  url: "http://radarr:7878"
  api_key: "YOUR_API_KEY"
  sync_enabled: true
  auto_add_unmatched: true  # auto-import unmatched folders to Radarr

sonarr:
  enabled: false
  url: "http://sonarr:8989"
  api_key: "YOUR_API_KEY"
  sync_enabled: true
```

> **Naming note**: Radarr mappings use `managed_root`/`library_root`. Sonarr mappings currently use `nested_root`/`shadow_root` (same concept, naming migration pending).

## Integration Checklist

- All containers (Radarr, Sonarr, LibrariArr) must mount the same top-level media root to `/data`.
- Keep managed folders and library folders under that shared root (e.g. `/data/movies`, `/data/radarr_library`).
- In Radarr: add each `library_root` as a root folder. In Sonarr: add each `shadow_root` as a root folder.
- Set up Radarr/Sonarr Connect webhooks to `http://librariarr:8787/api/hooks/radarr` (and `/hooks/sonarr`) for fast scoped reconcile.
- If API sync fails, check that all containers see the same paths (path parity).

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
