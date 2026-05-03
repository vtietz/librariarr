type ReconcileProgressFields = {
  movie_folders_seen?: number;
  series_folders_seen?: number;
  movie_items_targeted?: number | null;
  series_items_targeted?: number | null;
  movie_items_projected?: number;
  series_items_projected?: number;
  movie_items_processed?: number;
  series_items_processed?: number;
  movie_items_total?: number;
  series_items_total?: number;
  created_links?: number;
  matched_movies?: number;
  unmatched_movies?: number;
  matched_series?: number;
  unmatched_series?: number;
  affected_paths_count?: number | null;
};

export type DiscoveryWarningsResponse = {
  summary: {
    exclude_patterns_count: number;
    excluded_movie_candidates: number;
    duplicate_movie_candidates: number;
    orphaned_managed_movie_candidates: number;
  };
  exclude_paths: string[];
  excluded_movie_candidates: Array<{
    path: string;
    reason: string;
  }>;
  duplicate_movie_candidates: Array<{
    movie_ref: string;
    primary_path: string;
    duplicate_paths: string[];
    contains_excluded: boolean;
  }>;
  orphaned_managed_movie_candidates: Array<{
    path: string;
    reason: string;
  }>;
};

export type JobRecord = {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "canceled";
  queued_at: number;
  started_at: number | null;
  finished_at: number | null;
  updated_at: number;
  error: string | null;
  result: unknown;
  cancel_requested?: boolean;
  cancel_requested_at?: number | null;
  payload?: Record<string, unknown>;
};

export type JobsSummary = {
  queued: number;
  running: number;
  active: number;
  succeeded: number;
  failed: number;
  canceled?: number;
  latest_finished: JobRecord | null;
  updated_at: number;
};

export type RuntimeStatusResponse = {
  runtime_running: boolean;
  watched_nested_roots: number;
  watched_shadow_roots: number;
  watched_roots_total: number;
  debounce_seconds: number;
  dirty_paths_queued: number;
  next_event_reconcile_due_at: number | null;
  next_event_reconcile_in_seconds: number | null;
  current_task: {
    state: "idle" | "running" | "error";
    phase: string | null;
    trigger_source: string | null;
    started_at: number | null;
    updated_at: number | null;
    error: string | null;
    active_movie_root?: string | null;
    active_series_root?: string | null;
  } & ReconcileProgressFields;
  last_reconcile:
    | ({
        state: "ok" | "error";
        trigger_source: string | null;
        phase: string | null;
        started_at: number | null;
        finished_at: number | null;
        duration_seconds: number | null;
        followup_pending?: boolean;
        error: string | null;
        active_movie_root?: string | null;
        active_series_root?: string | null;
        full_reconcile_stats?: Record<string, number | string> | null;
      } & ReconcileProgressFields)
    | null;
  last_full_reconcile:
    | (ReconcileProgressFields & {
        state: "ok" | "error";
        full_reconcile_stats?: Record<string, number | string> | null;
        finished_at: number | null;
      })
    | null;
  library_root_stats?: Array<{
    library_root: string;
    managed_root: string;
    arr_type: string;
    planned: number;
    matched: number;
    skipped: number;
    projected_files: number;
    unchanged_files: number;
    skipped_files: number;
    updated_at: number;
  }>;
  known_links_in_memory?: number;
  mapped_cache?: {
    ready: boolean;
    building: boolean;
    updated_at_ms: number | null;
    entries_total: number;
    version: number;
    last_error: string | null;
    last_build_duration_ms?: number | null;
  };
  discovery_cache?: {
    ready: boolean;
    building: boolean;
    updated_at_ms: number | null;
    last_error: string | null;
    version: number;
    last_build_duration_ms?: number | null;
  };
  tasks_active_total?: number;
  pending_tasks?: Array<{
    id: string;
    name: string;
    status: "idle" | "queued" | "running" | "error";
    source: string;
    detail: string;
    queued_at: number | null;
    started_at: number | null;
    duration_seconds: number | null;
    next_run_at?: number | null;
    authoritative?: boolean;
  }>;
  health?: {
    status: "ok" | "degraded" | "starting" | string;
    reasons?: string[];
    worker_busy?: boolean;
    jobs_active?: number;
    consecutive_refresh_failures?: number;
    last_refresh_error?: string | null;
  };
  updated_at: number | null;
  runtime_supervisor_present: boolean;
  runtime_supervisor_running: boolean;
};

export type LogItem = {
  line: string;
  level: string;
  seq: string;
};