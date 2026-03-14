import axios from "axios";
import type { ConfigModel, ConfigResponse, ValidateResponse } from "../types/config";

const api = axios.create({
  baseURL: "/api",
  timeout: 10000
});

/** Short timeout for Arr metadata proxy calls (tags, profiles, etc.). */
const ARR_METADATA_TIMEOUT = 6000;

api.interceptors.response.use(
  (response) => {
    console.debug(
      `[API] ${response.config.method?.toUpperCase()} ${response.config.url} → ${response.status}`
    );
    return response;
  },
  (error) => {
    if (axios.isAxiosError(error)) {
      const status = error.response?.status ?? "no response";
      const detail =
        typeof error.response?.data === "object" &&
        error.response?.data !== null &&
        "detail" in error.response.data
          ? String(error.response.data.detail)
          : error.message;
      console.error(
        `[API] ${error.config?.method?.toUpperCase()} ${error.config?.url} → ${status}: ${detail}`
      );
    } else {
      console.error("[API] Request failed:", error);
    }
    return Promise.reject(error);
  }
);

export const getConfig = async (source: "disk" | "draft" = "disk") => {
  const { data } = await api.get<ConfigResponse>("/config", {
    params: { source, include_secrets: true }
  });
  return data;
};

export const validateConfig = async (config: ConfigModel) => {
  const { data } = await api.post<ValidateResponse>("/config/validate", {
    source: "disk",
    config
  });
  return data;
};

export const saveConfig = async (config: ConfigModel) => {
  const { data } = await api.put<ValidateResponse>("/config", { config }, {
    timeout: 15000
  });
  return data;
};

export const getDiff = async () => {
  const { data } = await api.get<{ has_diff: boolean; diff: string }>("/config/diff");
  return data;
};

export const getFsRoots = async () => {
  const { data } = await api.get<{ roots: string[] }>("/fs/roots");
  return data.roots;
};

export const listFs = async (path: string) => {
  const { data } = await api.get<{
    entries: Array<{ name: string; path: string; is_dir: boolean; is_symlink: boolean }>;
  }>("/fs/ls", { params: { path } });
  return data.entries;
};

export const getMappedDirectories = async (params?: {
  search?: string;
  shadowRoot?: string;
  limit?: number;
}) => {
  const { data } = await api.get<{
    items: Array<{
      shadow_root: string;
      virtual_path: string;
      real_path: string;
      target_exists: boolean;
    }>;
    shadow_roots: string[];
    truncated: boolean;
  }>("/fs/mapped-directories", {
    params: {
      search: params?.search,
      shadow_root: params?.shadowRoot,
      limit: params?.limit
    }
  });
  return data;
};

export const getMappedDirectoriesStreamUrl = (params?: { intervalMs?: number }) => {
  const search = new URLSearchParams();
  if (typeof params?.intervalMs === "number") {
    search.set("interval_ms", String(params.intervalMs));
  }
  const query = search.toString();
  return query
    ? `/api/fs/mapped-directories/stream?${query}`
    : "/api/fs/mapped-directories/stream";
};

export type DiscoveryWarningsResponse = {
  summary: {
    exclude_patterns_count: number;
    excluded_movie_candidates: number;
    duplicate_movie_candidates: number;
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
};

export const getDiscoveryWarnings = async (params?: { limit?: number }) => {
  const { data } = await api.get<DiscoveryWarningsResponse>("/fs/discovery-warnings", {
    params: {
      limit: params?.limit
    }
  });
  return data;
};

export const getRadarrProfiles = async () => {
  const { data } = await api.get<{ items: Array<{ id: number; name: string }> }>(
    "/radarr/quality-profiles",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getRadarrQualityDefinitions = async () => {
  const { data } = await api.get<{ items: Array<{ id: number; name?: string }> }>(
    "/radarr/quality-definitions",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getRadarrCustomFormats = async () => {
  const { data } = await api.get<{ items: Array<{ id: number; name: string }> }>(
    "/radarr/custom-formats",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getRadarrTags = async () => {
  const { data } = await api.get<{ items: Array<{ id?: number; label?: string }> }>(
    "/radarr/tags",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getSonarrProfiles = async () => {
  const { data } = await api.get<{ items: Array<{ id: number; name: string }> }>(
    "/sonarr/quality-profiles",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getSonarrLanguageProfiles = async () => {
  const { data } = await api.get<{
    enabled: boolean;
    items: Array<{ id: number; name: string }>;
    error: string | null;
  }>(
    "/sonarr/language-profiles",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data;
};

export const getSonarrTags = async () => {
  const { data } = await api.get<{ items: Array<{ id?: number; label?: string }> }>(
    "/sonarr/tags",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getRadarrRootFolders = async () => {
  const { data } = await api.get<{ items: Array<{ path: string }> }>(
    "/radarr/root-folders",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const getSonarrRootFolders = async () => {
  const { data } = await api.get<{ items: Array<{ path: string }> }>(
    "/sonarr/root-folders",
    { timeout: ARR_METADATA_TIMEOUT }
  );
  return data.items;
};

export const runRadarrDiagnostics = async () => {
  const queued = await enqueueJob("/diagnostics/radarr");
  const job = await waitForJob(queued.job_id);
  return parseJobResult<{
    status: string;
    issues: Array<{ severity: string; message: string }>;
  }>(job);
};

export const runSonarrDiagnostics = async () => {
  const queued = await enqueueJob("/diagnostics/sonarr");
  const job = await waitForJob(queued.job_id);
  return parseJobResult<{
    status: string;
    issues: Array<{ severity: string; message: string }>;
  }>(job);
};

export const testRadarrConnection = async (url: string, apiKey: string) => {
  const { data } = await api.post<{ ok: boolean; message: string }>("/radarr/test", {
    url,
    api_key: apiKey
  });
  return data;
};

export const testSonarrConnection = async (url: string, apiKey: string) => {
  const { data } = await api.post<{ ok: boolean; message: string }>("/sonarr/test", {
    url,
    api_key: apiKey
  });
  return data;
};

export const runDryRun = async () => {
  const queued = await enqueueJob("/dry-run");
  const job = await waitForJob(queued.job_id);
  return parseJobResult<{
    ok: boolean;
    summary?: {
      movie_folders_detected: number;
      series_folders_detected: number;
      root_mappings: number;
    };
    issues: Array<{ severity: string; message: string }>;
  }>(job);
};

export const runReconcileNow = async () => {
  const queued = await enqueueJob("/maintenance/reconcile");
  const job = await waitForJob(queued.job_id);
  return parseJobResult<{
    ok: boolean;
    message: string;
    duration_ms?: number;
    ingest_pending?: boolean;
  }>(job);
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

type JobQueuedResponse = {
  ok: boolean;
  queued: boolean;
  job_id: string;
  message: string;
};

const enqueueJob = async (path: string) => {
  const { data } = await api.post<JobQueuedResponse>(path);
  return data;
};

export const getJob = async (jobId: string) => {
  const { data } = await api.get<JobRecord>(`/jobs/${jobId}`);
  return data;
};

export const getJobsSummary = async () => {
  const { data } = await api.get<JobsSummary>("/jobs/summary");
  return data;
};

export const getJobs = async (params?: { limit?: number; status?: string }) => {
  const { data } = await api.get<{ items: JobRecord[] }>("/jobs", {
    params: {
      limit: params?.limit,
      status: params?.status
    }
  });
  return data.items;
};

export const cancelJob = async (jobId: string) => {
  const { data } = await api.post<{
    ok: boolean;
    job_id: string;
    status: string;
    message: string;
  }>(`/jobs/${jobId}/cancel`);
  return data;
};

export const waitForJob = async (
  jobId: string,
  options?: { intervalMs?: number; timeoutMs?: number }
) => {
  const intervalMs = Math.max(250, options?.intervalMs ?? 1000);
  const timeoutMs = Math.max(5000, options?.timeoutMs ?? 300000);
  const startedAt = Date.now();

  while (true) {
    const job = await getJob(jobId);
    if (job.status === "succeeded" || job.status === "failed" || job.status === "canceled") {
      return job;
    }
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error(`Timed out while waiting for job ${jobId}`);
    }
    await new Promise((resolve) => {
      window.setTimeout(resolve, intervalMs);
    });
  }
};

const parseJobResult = <T>(job: JobRecord): T => {
  if (job.status === "canceled") {
    throw new Error(job.error ?? "Background job was canceled.");
  }
  if (job.status === "failed") {
    throw new Error(job.error ?? "Background job failed.");
  }
  if (job.result == null) {
    throw new Error("Background job did not return a result.");
  }
  return job.result as T;
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
    pending_ingest_dirs?: number;
  };
  last_reconcile: {
    state: "ok" | "error";
    trigger_source: string | null;
    phase: string | null;
    started_at: number | null;
    finished_at: number | null;
    duration_seconds: number | null;
    ingest_pending: boolean;
    error: string | null;
    movie_folders_seen?: number;
    series_folders_seen?: number;
    created_links?: number;
    matched_movies?: number;
    unmatched_movies?: number;
    matched_series?: number;
    unmatched_series?: number;
    ingested_dirs?: number;
    pending_ingest_dirs?: number;
  } | null;
  updated_at: number | null;
  runtime_supervisor_present: boolean;
  runtime_supervisor_running: boolean;
};

export const getRuntimeStatus = async () => {
  const { data } = await api.get<RuntimeStatusResponse>("/runtime/status");
  return data;
};

export type LogItem = {
  line: string;
  level: string;
  seq: string;
};

export const getAppLogs = async (params?: { tail?: number; timeoutMs?: number }) => {
  const { data } = await api.get<{
    tail: number;
    items: LogItem[];
  }>("/logs", {
    params: {
      tail: params?.tail
    },
    timeout: params?.timeoutMs ?? 8000
  });
  return data;
};

export const getAppLogStreamUrl = () => {
  return "/api/logs/stream";
};
