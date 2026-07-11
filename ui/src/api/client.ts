import axios from "axios";

export interface ActionEntry {
  kind: string;
  detail: string;
  source: string | null;
  target: string | null;
}

export interface UnmatchedEntry {
  path: string;
  parsed_title: string | null;
  parsed_year: number | null;
  reason: string;
  candidates: string[];
}

export interface ReconcileReport {
  dry_run: boolean;
  scope: string;
  stats: Record<string, number>;
  items_seen: number;
  items_changed: number;
  duration_seconds: number;
  actions: ActionEntry[];
  unmatched: UnmatchedEntry[];
  warnings: string[];
  errors: string[];
}

export interface ProgressInfo {
  phase: string;
  current: number;
  total: number;
}

export interface RunSummary {
  finished_at: number;
  scope: string;
  dry_run?: boolean;
  items_seen?: number;
  items_changed?: number;
  unmatched?: number;
  warnings?: number;
  errors?: number;
  duration_seconds?: number;
  error?: string;
}

export interface StatusResponse {
  running: boolean;
  running_scope: string | null;
  started_at: number | null;
  progress: ProgressInfo | null;
  last_finished_at: number | null;
  last_error: string | null;
  last_report: ReconcileReport | null;
  last_full_report: ReconcileReport | null;
  last_full_finished_at: number | null;
  history: RunSummary[];
  runtime_loop_active: boolean;
}

export interface ManualAddResult {
  ok: boolean;
  reason?: string;
  detail?: string | null;
  candidates?: string[];
  actions?: string[];
}

export interface LogEntry {
  line: string;
  level: string;
  seq: string;
}

export interface PathDifference {
  kind: "movie" | "series";
  title: string | null;
  arr_path: string;
  managed_path: string;
}

const api = axios.create({ baseURL: "/api" });

export const getStatus = () => api.get<StatusResponse>("/status").then((r) => r.data);

export interface UnmatchedResponse {
  unmatched: UnmatchedEntry[];
  as_of: number | null;
}

export const getUnmatched = () =>
  api.get<UnmatchedResponse>("/unmatched").then((r) => r.data);

export const manualAdd = (path: string) =>
  api.post<ManualAddResult>("/unmatched/add", { path }).then((r) => r.data);

export const triggerReconcile = (scope: "full" | "consistency", dryRun = false) =>
  api
    .post<{ ok: boolean; queued?: boolean; report?: ReconcileReport }>("/reconcile", {
      scope,
      dry_run: dryRun
    })
    .then((r) => r.data);

export const getConfigYaml = () =>
  api.get<{ yaml: string }>("/config").then((r) => r.data.yaml);

export const validateConfigYaml = (yaml: string) =>
  api
    .post<{ valid: boolean; error: string | null }>("/config/validate", { yaml })
    .then((r) => r.data);

export const saveConfigYaml = (yaml: string) =>
  api.put<{ ok: boolean; note?: string }>("/config", { yaml }).then((r) => r.data);

export const getLogs = (limit = 300) =>
  api
    .get<{ entries: LogEntry[] }>("/logs", { params: { limit } })
    .then((r) => r.data.entries);

export const getPathDifferences = () =>
  api
    .get<{ differences: PathDifference[] }>("/path-differences")
    .then((r) => r.data.differences);
