import { type Dispatch, type SetStateAction, useCallback, useEffect, useState } from "react";
import { runMaintenanceReconcile, waitForJobCompletion } from "../api/client";
import type { MappedDirectory } from "./DirectoryMapperRows";

function normalizeRealPath(value: string): string {
  const normalized = value.trim().replace(/\\/g, "/");
  if (normalized.length > 1) {
    return normalized.replace(/\/+$/, "");
  }
  return normalized;
}

type ScopedPathOutcome = {
  status?: string;
  arr?: string;
  message?: string;
  movie_id?: number | null;
  series_id?: number | null;
};

type Params = {
  setIsReconciling: (value: boolean) => void;
  setReconcilingPath: (path: string | null) => void;
  setLoadError: (message: string | null) => void;
  setMappedDirectories: Dispatch<SetStateAction<MappedDirectory[]>>;
  loadMappedDirectories: () => Promise<void>;
  loadDiscoveryWarnings: () => Promise<void>;
};

export function useReconcileActions({
  setIsReconciling,
  setReconcilingPath,
  setLoadError,
  setMappedDirectories,
  loadMappedDirectories,
  loadDiscoveryWarnings
}: Params) {
  const [recentlyReconciledPath, setRecentlyReconciledPath] = useState<string | null>(null);

  const applyScopedReconcileOutcome = useCallback(
    (path: string, outcome: ScopedPathOutcome): boolean => {
      const normalizedTargetPath = normalizeRealPath(path);
      let matched = false;
      setMappedDirectories((previous) =>
        previous.map((entry) => {
          if (normalizeRealPath(entry.real_path) !== normalizedTargetPath) {
            return entry;
          }
          matched = true;
          return {
            ...entry,
            last_reconcile_status: outcome.status ?? entry.last_reconcile_status,
            last_reconcile_arr: outcome.arr ?? entry.last_reconcile_arr,
            last_reconcile_message: outcome.message ?? entry.last_reconcile_message,
            last_reconcile_movie_id:
              typeof outcome.movie_id === "number"
                ? outcome.movie_id
                : (entry.last_reconcile_movie_id ?? null),
            last_reconcile_series_id:
              typeof outcome.series_id === "number"
                ? outcome.series_id
                : (entry.last_reconcile_series_id ?? null),
            last_reconcile_updated_at_ms: Date.now()
          };
        })
      );
      return matched;
    },
    [setMappedDirectories]
  );

  const extractResult = (
    raw: unknown
  ): {
    ok?: boolean;
    message?: string;
    path_outcome?: ScopedPathOutcome;
  } | null => {
    if (typeof raw !== "object" || raw === null) {
      return null;
    }
    const payload = raw as {
      ok?: unknown;
      message?: unknown;
      path_outcome?: {
        status?: unknown;
        arr?: unknown;
        message?: unknown;
        movie_id?: unknown;
        series_id?: unknown;
      };
    };
    return {
      ok: typeof payload.ok === "boolean" ? payload.ok : undefined,
      message: typeof payload.message === "string" ? payload.message : undefined,
      path_outcome:
        typeof payload.path_outcome === "object" && payload.path_outcome !== null
          ? {
              status:
                typeof payload.path_outcome.status === "string"
                  ? payload.path_outcome.status
                  : undefined,
              arr:
                typeof payload.path_outcome.arr === "string"
                  ? payload.path_outcome.arr
                  : undefined,
              message:
                typeof payload.path_outcome.message === "string"
                  ? payload.path_outcome.message
                  : undefined,
              movie_id:
                typeof payload.path_outcome.movie_id === "number"
                  ? payload.path_outcome.movie_id
                  : null,
              series_id:
                typeof payload.path_outcome.series_id === "number"
                  ? payload.path_outcome.series_id
                  : null
            }
          : undefined
    };
  };

  useEffect(() => {
    if (recentlyReconciledPath === null) {
      return;
    }
    const timer = window.setTimeout(() => {
      setRecentlyReconciledPath(null);
    }, 1800);
    return () => {
      window.clearTimeout(timer);
    };
  }, [recentlyReconciledPath]);

  const queueReconcile = useCallback(async () => {
    setIsReconciling(true);
    setLoadError(null);
    try {
      const scheduled = await runMaintenanceReconcile();
      if (!scheduled.job_id) {
        throw new Error("Reconcile job was not scheduled.");
      }
      const completed = await waitForJobCompletion(scheduled.job_id);
      const result = extractResult(completed.result);
      if (result?.ok === false) {
        throw new Error(result.message ?? "Reconcile failed.");
      }
      await loadMappedDirectories();
      await loadDiscoveryWarnings();
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? `Reconcile failed: ${error.message}`
          : "Reconcile failed unexpectedly."
      );
    } finally {
      setIsReconciling(false);
    }
  }, [loadDiscoveryWarnings, loadMappedDirectories, setIsReconciling, setLoadError]);

  const reconcilePath = useCallback(
    async (path: string) => {
      setReconcilingPath(path);
      setLoadError(null);
      try {
        const scheduled = await runMaintenanceReconcile({ path });
        if (!scheduled.job_id) {
          throw new Error("Scoped reconcile job was not scheduled.");
        }
        const completed = await waitForJobCompletion(scheduled.job_id);
        const result = extractResult(completed.result);
        if (result?.ok === false) {
          throw new Error(result.message ?? "Scoped reconcile failed.");
        }
        const appliedLocally = result?.path_outcome
          ? applyScopedReconcileOutcome(path, result.path_outcome)
          : false;
        if (!appliedLocally) {
          await loadMappedDirectories();
        }
        if (result?.path_outcome?.status === "success") {
          setRecentlyReconciledPath(path);
        }
      } catch (error) {
        setLoadError(
          error instanceof Error
            ? `Scoped reconcile failed: ${error.message}`
            : "Scoped reconcile failed unexpectedly."
        );
      } finally {
        setReconcilingPath(null);
      }
    },
    [
      loadMappedDirectories,
      applyScopedReconcileOutcome,
      setLoadError,
      setReconcilingPath
    ]
  );

  return { queueReconcile, reconcilePath, recentlyReconciledPath };
}
