import { useCallback, useEffect, useState } from "react";
import { runMaintenanceReconcile, waitForJobCompletion } from "../api/client";

type Params = {
  setIsReconciling: (value: boolean) => void;
  setReconcilingPath: (path: string | null) => void;
  setLoadError: (message: string | null) => void;
  loadMappedDirectories: () => Promise<void>;
  loadDiscoveryWarnings: () => Promise<void>;
};

export function useReconcileActions({
  setIsReconciling,
  setReconcilingPath,
  setLoadError,
  loadMappedDirectories,
  loadDiscoveryWarnings
}: Params) {
  const [recentlyReconciledPath, setRecentlyReconciledPath] = useState<string | null>(null);

  const extractResult = (raw: unknown): { ok?: boolean; message?: string; path_outcome?: { status?: string } } | null => {
    if (typeof raw !== "object" || raw === null) {
      return null;
    }
    const payload = raw as {
      ok?: unknown;
      message?: unknown;
      path_outcome?: { status?: unknown };
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
                  : undefined
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
        await loadMappedDirectories();
        await loadDiscoveryWarnings();
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
      loadDiscoveryWarnings,
      loadMappedDirectories,
      setLoadError,
      setReconcilingPath
    ]
  );

  return { queueReconcile, reconcilePath, recentlyReconciledPath };
}
