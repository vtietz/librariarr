import type { MappedDirectory } from "./DirectoryMapperRows";

export const sortMappedDirectories = (items: MappedDirectory[]) =>
  [...items].sort((left, right) => {
    const rootCompare = left.shadow_root.localeCompare(right.shadow_root);
    if (rootCompare !== 0) {
      return rootCompare;
    }
    const virtualCompare = left.virtual_path.localeCompare(right.virtual_path);
    if (virtualCompare !== 0) {
      return virtualCompare;
    }
    return left.real_path.localeCompare(right.real_path);
  });

export const mappedDirectoriesErrorMessage = (error: unknown): string => {
  const detail =
    typeof error === "object" &&
    error !== null &&
    "response" in error &&
    typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail ===
      "string"
      ? ((error as { response: { data: { detail: string } } }).response.data.detail ?? null)
      : null;

  const timedOut =
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: string }).code === "ECONNABORTED";

  return (
    detail ||
    (timedOut
      ? "Snapshot request timed out. The backend may still be rebuilding/scanning or serializing a large index; wait briefly or trigger a full reconcile."
      : "Failed to load mapped directories.")
  );
};

export const mergeMappedDirectoriesByVirtualPath = (
  baseItems: MappedDirectory[],
  enrichedItems: MappedDirectory[]
) => {
  const mergedByVirtualPath = new Map<string, MappedDirectory>();

  for (const item of baseItems) {
    mergedByVirtualPath.set(item.virtual_path, item);
  }

  for (const enriched of enrichedItems) {
    const existing = mergedByVirtualPath.get(enriched.virtual_path);
    if (!existing) {
      mergedByVirtualPath.set(enriched.virtual_path, enriched);
      continue;
    }
    mergedByVirtualPath.set(enriched.virtual_path, {
      ...existing,
      ...enriched
    });
  }

  return Array.from(mergedByVirtualPath.values());
};

export const mappedCacheStatusText = (params: {
  reconcilingPath: string | null;
  isReconciling: boolean;
  cacheBuilding: boolean;
  cacheReady: boolean;
  cacheUpdatedAtMs: number | null;
}) => {
  const { reconcilingPath, isReconciling, cacheBuilding, cacheReady, cacheUpdatedAtMs } = params;

  if (reconcilingPath) {
    return "Reconciling selected path...";
  }
  if (isReconciling) {
    return "Reconciling whole library...";
  }
  if (cacheBuilding && !cacheReady) {
    return "Indexing in progress";
  }
  if (!cacheReady) {
    return "Index not ready";
  }
  if (typeof cacheUpdatedAtMs !== "number") {
    return "Index ready";
  }

  const elapsedSec = Math.max(0, Math.floor((Date.now() - cacheUpdatedAtMs) / 1000));
  if (elapsedSec < 60) {
    return `Index ready · updated ${elapsedSec}s ago`;
  }
  const elapsedMin = Math.floor(elapsedSec / 60);
  if (elapsedMin < 60) {
    return `Index ready · updated ${elapsedMin}m ago`;
  }
  const elapsedHours = Math.floor(elapsedMin / 60);
  return `Index ready · updated ${elapsedHours}h ago`;
};
