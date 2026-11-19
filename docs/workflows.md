# Runtime Workflows

Canonical scenario semantics live in
[reconciliation_scenarios.md](reconciliation_scenarios.md); architecture in
[architecture.md](architecture.md). This page summarizes when which pass runs.

## Triggers

| Trigger | Pass | Latency |
|---|---|---|
| Webhook naming an item (`POST /api/hooks/{radarr,sonarr}` with `movie.id`/`series.id`) | targeted, that item only | `runtime.debounce_seconds` (default 8s) |
| Webhook without a usable item id (test/health events, unexpected payloads) | consistency | `runtime.debounce_seconds` |
| Interval | bucket-drift poll → targeted for drifted items | every `runtime.bucket_drift_interval_seconds` (default 300s; `0` disables) |
| Interval (`schedule_mode: interval`, default) | consistency | every `runtime.consistency_interval_seconds` (default 300s) |
| Interval (`schedule_mode: interval`, default) | full | every `runtime.full_interval_minutes` (default 1440m / daily) |
| Daily (`schedule_mode: daily`) | full, replacing both interval passes | once per day at `runtime.daily_full_time` in `runtime.daily_timezone` |
| Startup | `runtime.startup_scope` (default full) | immediate |
| API (`POST /api/reconcile`) | chosen scope | queued into the loop (or immediate with `dry_run`) |

There are no filesystem watchers. Arr-side changes arrive via webhooks within
seconds and cost only the named item — the full pass isn't involved at all for
downloads/upgrades, so its interval can be long without affecting how fast
Arr-driven changes show up. The interval consistency pass stays as the safety
net: it is what heals anything a lost or unidentifiable webhook would otherwise
leave unreconciled, so it should not be disabled just because targeted passes
handle the common case.

One Arr-side change has no webhook at all — reassigning an item's root folder
(`MovieMovedEvent` never reaches notification providers). That is what the
bucket-drift poll is for: one Arr list call, no tree walk, and only the drifted
items get reconciled.

User-side changes (manual folder drops, moves, renames) are only picked up by
the next full pass, since discovering them requires the one tree walk that
pass does. If daily is too slow for how often you reorganize by hand, lower
`full_interval_minutes`, or just click **Run full pass now** in the Status
panel (or `POST /api/reconcile {"scope": "full"}`) right after making changes
— that's the intended way to get immediate convergence without lowering the
scheduled interval for everyone.

### Daily Schedule Mode (low idle disk access)

`runtime.schedule_mode: daily` exists so the managed disks can spin down
between jobs. It replaces the periodic consistency and full passes with one
full pass per day — the full pass already covers known-item consistency plus
discovery and prune, so nothing between slots touches the managed tree. For a
fully idle setup also set `bucket_drift_interval_seconds: 0` (root-folder
reassignments then wait for the daily pass) and `startup_scope: "off"`.

- Targeted webhook passes and manual runs (`POST /api/reconcile`, the UI
  buttons) work at any hour. They neither postpone the daily slot nor count
  as it; a webhook without an item id still runs a consistency pass.
- Each slot is identified by its local date and recorded in
  `librariarr-schedule.json` next to the id cache. A slot that already
  succeeded is never repeated after a restart.
- A slot that passed while LibrariArr was down is **not** caught up on
  startup (a restart must not walk the tree). It is logged and shown as
  *missed* in `/api/status` → `schedule` and the Status panel, and the next
  slot covers it.
- A pass that raises, or returns a report carrying errors, is recorded as
  failed (logged, shown in status with the error). It is retried after
  `daily_retry_minutes` (default 60), never sooner and never past the next
  slot. A pending retry survives a restart, and may run right at startup if
  its time has already passed.

Triggers that land in the same debounce window collapse into one pass, and the
broader scope wins: several webhooks for the same movie run once, and a
consistency trigger arriving alongside them supersedes the ids entirely. A
targeted pass deliberately does *not* reset the consistency timer (or the
daily slot) — otherwise continuous webhook traffic would starve the safety net.

## Pass Contents

**Targeted** (one or more named Arr items):
1. Fetch only those ids (`get_movies_by_ids`/`get_series_by_ids`). An Arr with
   no ids in the request is not contacted at all.
2. The per-item flow below, unchanged.
3. No pruning and no discovery — both need a complete item list or the tree
   walk.

**Consistency** (cheap, no tree walk):
1. Fetch all movies/series (+episode files) from Arr.
2. Per item: verify library-file inode against the cached managed folder.
3. Ingest new imports/upgrades (hardlink into managed), relink user
   replacements, restore missing library files, sync per-item projections,
   follow Arr-side bucket changes.

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
