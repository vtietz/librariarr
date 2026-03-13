import axios from "axios";
import type { ConfigModel, ConfigResponse, ValidateResponse } from "../types/config";

const api = axios.create({
  baseURL: "/api"
});

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
  const { data } = await api.put<ValidateResponse>("/config", { config });
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

export const getRadarrProfiles = async () => {
  const { data } = await api.get<{ items: Array<{ id: number; name: string }> }>(
    "/radarr/quality-profiles"
  );
  return data.items;
};

export const getSonarrProfiles = async () => {
  const { data } = await api.get<{ items: Array<{ id: number; name: string }> }>(
    "/sonarr/quality-profiles"
  );
  return data.items;
};

export const getRadarrRootFolders = async () => {
  const { data } = await api.get<{ items: Array<{ path: string }> }>("/radarr/root-folders");
  return data.items;
};

export const getSonarrRootFolders = async () => {
  const { data } = await api.get<{ items: Array<{ path: string }> }>("/sonarr/root-folders");
  return data.items;
};

export const runRadarrDiagnostics = async () => {
  const { data } = await api.post<{
    status: string;
    issues: Array<{ severity: string; message: string }>;
  }>("/diagnostics/radarr");
  return data;
};

export const runSonarrDiagnostics = async () => {
  const { data } = await api.post<{
    status: string;
    issues: Array<{ severity: string; message: string }>;
  }>("/diagnostics/sonarr");
  return data;
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
  const { data } = await api.post<{
    ok: boolean;
    summary?: {
      movie_folders_detected: number;
      series_folders_detected: number;
      root_mappings: number;
    };
    issues: Array<{ severity: string; message: string }>;
  }>("/dry-run");
  return data;
};

export const runReconcileNow = async () => {
  const { data } = await api.post<{
    ok: boolean;
    message: string;
    duration_ms?: number;
    ingest_pending?: boolean;
  }>("/maintenance/reconcile");
  return data;
};

export type DockerLogItem = {
  line: string;
  level: string;
};

export const getDockerLogs = async (params?: { container?: string; tail?: number }) => {
  const { data } = await api.get<{
    container: string;
    tail: number;
    items: DockerLogItem[];
  }>("/logs/docker", {
    params: {
      container: params?.container,
      tail: params?.tail
    }
  });
  return data;
};

export const getDockerLogStreamUrl = (params?: { container?: string; tail?: number }) => {
  const search = new URLSearchParams();
  if (params?.container) {
    search.set("container", params.container);
  }
  if (typeof params?.tail === "number") {
    search.set("tail", String(params.tail));
  }
  const query = search.toString();
  return query ? `/api/logs/docker/stream?${query}` : "/api/logs/docker/stream";
};
