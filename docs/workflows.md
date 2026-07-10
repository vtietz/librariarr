# Runtime Workflows

Canonical scenario semantics live in
[reconciliation_scenarios.md](reconciliation_scenarios.md); architecture in
[architecture.md](architecture.md). This page summarizes when which pass runs.

## Triggers

| Trigger | Pass | Latency |
|---|---|---|
| Radarr/Sonarr Connect webhook (`POST /api/hooks/{radarr,sonarr}`) | consistency | `runtime.debounce_seconds` (default 8s) |
| Interval | consistency | every `runtime.consistency_interval_seconds` (default 300s) |
| Interval | full | every `runtime.full_interval_minutes` (default 1440m / daily) |
| Startup | `runtime.startup_scope` (default full) | immediate |
| API (`POST /api/reconcile`) | chosen scope | queued into the loop (or immediate with `dry_run`) |

There are no filesystem watchers. Arr-side changes arrive via webhooks within
seconds — the full pass isn't involved at all for downloads/upgrades, so its
interval can be long without affecting how fast Arr-driven changes show up.
User-side changes (manual folder drops, moves, renames) are only picked up by
the next full pass, since discovering them requires the one tree walk that
pass does. If daily is too slow for how often you reorganize by hand, lower
`full_interval_minutes`, or just click **Run full pass now** in the Status
panel (or `POST /api/reconcile {"scope": "full"}`) right after making changes
— that's the intended way to get immediate convergence without lowering the
scheduled interval for everyone.

## Pass Contents

**Consistency** (cheap, no tree walk):
1. Fetch all movies/series (+episode files) from Arr.
2. Per item: verify library-file inode against the cached managed folder.
3. Ingest new imports/upgrades (hardlink into managed), relink user
   replacements, restore missing library files, sync per-item projections.

**Full** (one managed-tree walk):
1. Build the inode index across managed roots.
2. Everything the consistency pass does, plus resolving items without cache
   hints (user moves).
3. Discovery: report/auto-add/adopt unmatched managed folders.
4. Prune stale library/shadow folders (items removed from Arr).

## Deployment Notes

- Webhooks: point Radarr/Sonarr Connect at
  `http://librariarr:8787/api/hooks/radarr` / `.../sonarr`. Optional shared
  secret via `LIBRARIARR_WEBHOOK_SECRET` (header
  `X-Librariarr-Webhook-Secret`).
- `--once` runs a single full pass and prints the report as JSON;
  `--once --dry-run` prints the plan without touching anything.
- `--web` serves the UI/API and runs the loop; `--web-no-runtime` serves the
  API only.
