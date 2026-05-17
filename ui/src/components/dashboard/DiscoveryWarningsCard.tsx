import {
  ActionIcon,
  Badge,
  Card,
  Group,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconBan,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";
import {
  getConfig,
  getDiscoveryWarnings,
  getFsRoots,
  getUnmatchedMovieCandidates,
  recycleOrphanedManagedFolder,
  resolveUnmatchedMovieMapping,
  runMaintenanceReconcile,
  saveConfig,
  waitForJobCompletion,
} from "../../api/client";
import type { UnmatchedMovieCandidatesResponse } from "../../api/client";
import ImportErrorModal from "./ImportErrorModal";
import UnmatchedResolveModal from "./UnmatchedResolveModal";
import DirectoryPickerModal from "../DirectoryPickerModal";
import DiscoveryWarningsSections from "./DiscoveryWarningsSections";

type DiscoveryWarnings = Awaited<ReturnType<typeof getDiscoveryWarnings>>;

type Props = {
  discoveryWarnings: DiscoveryWarnings | null;
  onRefreshWarnings: () => Promise<void>;
};

export default function DiscoveryWarningsCard({ discoveryWarnings, onRefreshWarnings }: Props) {
  const excludedCandidates = discoveryWarnings?.summary.excluded_movie_candidates ?? 0;
  const duplicateCandidates = discoveryWarnings?.summary.duplicate_movie_candidates ?? 0;
  const orphanedManagedCandidates =
    discoveryWarnings?.summary.orphaned_managed_movie_candidates ?? 0;
  const unmatchedManagedCandidates =
    discoveryWarnings?.summary.unmatched_managed_movie_candidates ?? 0;
  const unmanagedShadowVideoFiles =
    discoveryWarnings?.summary.unmanaged_shadow_video_files ?? 0;
  const excludedItems = discoveryWarnings?.excluded_movie_candidates ?? [];
  const duplicateItems = discoveryWarnings?.duplicate_movie_candidates ?? [];
  const orphanedItems = discoveryWarnings?.orphaned_managed_movie_candidates ?? [];
  const unmatchedItems = discoveryWarnings?.unmatched_managed_movie_candidates ?? [];
  const unmanagedShadowItems = discoveryWarnings?.unmanaged_shadow_video_files ?? [];
  const hasDiscoveryWarnings =
    excludedCandidates > 0 ||
    duplicateCandidates > 0 ||
    orphanedManagedCandidates > 0 ||
    unmatchedManagedCandidates > 0 ||
    unmanagedShadowVideoFiles > 0;
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [fsRoots, setFsRoots] = useState<string[]>([]);
  const [loadingRoots, setLoadingRoots] = useState(false);
  const [busyOrphanPath, setBusyOrphanPath] = useState<string | null>(null);
  const [busyImportPath, setBusyImportPath] = useState<string | null>(null);
  const [importInFlightByPath, setImportInFlightByPath] = useState<Record<string, boolean>>({});
  const [importStatusByPath, setImportStatusByPath] = useState<
    Record<string, { color: string; message: string }>
  >({});
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [importErrorsByPath, setImportErrorsByPath] = useState<Record<string, string>>({});
  const [busyIgnorePath, setBusyIgnorePath] = useState<string | null>(null);
  const [ignoreStatusByPath, setIgnoreStatusByPath] = useState<
    Record<string, { color: string; message: string }>
  >({});
  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null);
  const [importErrorDialogPath, setImportErrorDialogPath] = useState<string | null>(null);
  const [resolveDialogPath, setResolveDialogPath] = useState<string | null>(null);
  const [resolveCandidates, setResolveCandidates] =
    useState<UnmatchedMovieCandidatesResponse | null>(null);
  const [resolveLoading, setResolveLoading] = useState(false);
  const [resolveError, setResolveError] = useState<string>("");
  const [selectedResolveMovieId, setSelectedResolveMovieId] = useState<string>("");
  const [resolveForceTakeover, setResolveForceTakeover] = useState(false);

  const warningRowStyle = (rowKey: string) => ({
    flex: 1,
    minWidth: 0,
    borderRadius: "6px",
    padding: "4px 6px",
    backgroundColor:
      hoveredRowKey === rowKey ? "rgba(120, 130, 145, 0.08)" : "transparent",
    transition: "background-color 120ms ease"
  });

  const parseApiErrorMessage = (error: unknown, fallback: string) => {
    const detail =
      typeof error === "object" &&
      error !== null &&
      "response" in error &&
      typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail ===
        "string"
        ? ((error as { response: { data: { detail: string } } }).response.data.detail ?? "")
        : "";
    return detail.trim() || fallback;
  };

  const browseRoots = useMemo(() => {
    if (fsRoots.length > 0) {
      return fsRoots;
    }
    return browsePath ? [browsePath] : [];
  }, [browsePath, fsRoots]);

  const excludePathSet = useMemo(() => {
    return new Set((discoveryWarnings?.exclude_paths ?? []).map((item) => item.toLowerCase()));
  }, [discoveryWarnings?.exclude_paths]);

  const ensureFsRoots = async () => {
    if (fsRoots.length > 0 || loadingRoots) {
      return;
    }
    setLoadingRoots(true);
    try {
      const roots = await getFsRoots();
      setFsRoots(roots);
    } catch (error) {
      console.error("[DiscoveryWarnings] failed to load filesystem roots", error);
    } finally {
      setLoadingRoots(false);
    }
  };

  const handleOpenFolder = async (path: string) => {
    setRowErrors((current) => ({ ...current, [path]: "" }));
    await ensureFsRoots();
    setBrowsePath(path);
  };

  const handleRecycleOrphan = async (path: string) => {
    const confirmed = window.confirm(
      "Recycle this orphaned folder? This moves it into .deletedByLibrariarr."
    );
    if (!confirmed) {
      return;
    }

    setBusyOrphanPath(path);
    setRowErrors((current) => ({ ...current, [path]: "" }));
    try {
      await recycleOrphanedManagedFolder(path);
    } catch (error) {
      console.error("[DiscoveryWarnings] recycle orphaned folder failed", error);
      setRowErrors((current) => ({
        ...current,
        [path]: "Recycle failed. The folder may no longer be orphaned.",
      }));
      return;
    }

    try {
      await onRefreshWarnings();
    } catch (error) {
      console.error("[DiscoveryWarnings] warning refresh failed after recycle", error);
      setRowErrors((current) => ({
        ...current,
        [path]: "Folder recycled, but refresh failed. Please reload warnings.",
      }));
    } finally {
      setBusyOrphanPath(null);
    }
  };

  const handleImportUnmatched = async (path: string) => {
    setResolveDialogPath(path);
    setResolveCandidates(null);
    setResolveError("");
    setSelectedResolveMovieId("");
    setResolveForceTakeover(false);
    setResolveLoading(true);
    try {
      const payload = await getUnmatchedMovieCandidates(path);
      setResolveCandidates(payload);
      if (payload.candidates.length > 0) {
        setSelectedResolveMovieId(String(payload.candidates[0].movie_id));
      }
    } catch (error) {
      setResolveError(parseApiErrorMessage(error, "Failed to load candidate movies."));
    } finally {
      setResolveLoading(false);
    }
  };

  const handleResolveAndImportUnmatched = async () => {
    if (!resolveDialogPath) {
      return;
    }
    const targetPath = resolveDialogPath;

    if (!selectedResolveMovieId) {
      setResolveError("Select a movie before applying this mapping.");
      return;
    }

    const selectedMovieId = Number.parseInt(selectedResolveMovieId, 10);
    if (!Number.isFinite(selectedMovieId)) {
      setResolveError("Selected movie is invalid.");
      return;
    }

    setBusyImportPath(targetPath);
    setImportInFlightByPath((current) => ({ ...current, [targetPath]: true }));
    setImportStatusByPath((current) => ({
      ...current,
      [targetPath]: { color: "blue", message: "Queueing import in Radarr..." },
    }));
    setImportErrorsByPath((current) => ({ ...current, [targetPath]: "" }));
    try {
      await resolveUnmatchedMovieMapping({
        path: targetPath,
        movieId: selectedMovieId,
        forceTakeover: resolveForceTakeover,
      });

      setImportStatusByPath((current) => ({
        ...current,
        [targetPath]: { color: "blue", message: "Mapping saved. Queueing reconcile..." },
      }));

      const queued = await runMaintenanceReconcile({ path: targetPath });
      setImportStatusByPath((current) => ({
        ...current,
        [targetPath]: {
          color: "blue",
          message: `Import queued (job ${queued.job_id.slice(0, 8)}...)`,
        },
      }));
      setImportErrorDialogPath((current) => (current === targetPath ? null : current));
      setResolveDialogPath(null);

      void (async () => {
        try {
          await waitForJobCompletion(queued.job_id, { timeoutMs: 180000, pollIntervalMs: 1500 });
          setImportStatusByPath((current) => ({
            ...current,
            [targetPath]: { color: "green", message: "Import finished successfully." },
          }));
          setImportErrorsByPath((current) => ({ ...current, [targetPath]: "" }));
          await onRefreshWarnings();
        } catch (error) {
          const message = parseApiErrorMessage(error, "Import failed after being queued.");
          setImportErrorsByPath((current) => ({ ...current, [targetPath]: message }));
          setImportStatusByPath((current) => ({
            ...current,
            [targetPath]: { color: "red", message },
          }));
          setImportErrorDialogPath(targetPath);
        } finally {
          setImportInFlightByPath((current) => ({ ...current, [targetPath]: false }));
        }
      })();

      try {
        await onRefreshWarnings();
      } catch (error) {
        console.error("[DiscoveryWarnings] warning refresh failed after import trigger", error);
      }
    } catch (error) {
      const message = parseApiErrorMessage(
        error,
        "Import trigger failed. Open details and retry."
      );
      setImportErrorsByPath((current) => ({ ...current, [targetPath]: message }));
      setImportStatusByPath((current) => ({
        ...current,
        [targetPath]: { color: "red", message },
      }));
      setImportErrorDialogPath(targetPath);
      setResolveError(message);
    } finally {
      setBusyImportPath((current) => (current === targetPath ? null : current));
    }
  };

  const handleIgnorePath = async (path: string) => {
    setBusyIgnorePath(path);
    setIgnoreStatusByPath((current) => ({
      ...current,
      [path]: { color: "blue", message: "Saving ignore path..." },
    }));

    try {
      const payload = await getConfig("disk");
      const existing = payload.config.paths.exclude_paths ?? [];
      const normalizedExisting = existing
        .map((item) => item.trim())
        .filter((item) => item.length > 0);
      const alreadyIgnored = normalizedExisting.some(
        (item) => item.toLowerCase() === path.toLowerCase()
      );

      if (!alreadyIgnored) {
        await saveConfig({
          ...payload.config,
          paths: {
            ...payload.config.paths,
            exclude_paths: [...normalizedExisting, path],
          },
        });
      }

      setIgnoreStatusByPath((current) => ({
        ...current,
        [path]: {
          color: alreadyIgnored ? "yellow" : "green",
          message: alreadyIgnored
            ? "Path already present in paths.exclude_paths."
            : "Path added to paths.exclude_paths.",
        },
      }));

      await onRefreshWarnings();
    } catch (error) {
      setIgnoreStatusByPath((current) => ({
        ...current,
        [path]: {
          color: "red",
          message: parseApiErrorMessage(error, "Failed to save ignore path."),
        },
      }));
    } finally {
      setBusyIgnorePath((current) => (current === path ? null : current));
    }
  };

  const importDialogError =
    importErrorDialogPath !== null ? importErrorsByPath[importErrorDialogPath] ?? "" : "";

  const renderIgnoreAction = (path: string, label: string) => (
    <Tooltip label={label} withArrow>
      <ActionIcon
        size="sm"
        color={excludePathSet.has(path.toLowerCase()) ? "yellow" : "gray"}
        variant="light"
        onClick={() => void handleIgnorePath(path)}
        disabled={busyIgnorePath === path}
        aria-label="Ignore folder path"
      >
        <IconBan size={14} />
      </ActionIcon>
    </Tooltip>
  );

  return (
    <Card withBorder>
      <Group justify="space-between">
        <Text fw={600}>Discovery Warnings</Text>
        <Badge color={hasDiscoveryWarnings ? "yellow" : "green"}>
          {hasDiscoveryWarnings ? "needs attention" : "clear"}
        </Badge>
      </Group>
      <Text size="sm" c="dimmed" mt="xs">
        {excludedCandidates} excluded movie candidates · {duplicateCandidates} potential duplicates ·{" "}
        {orphanedManagedCandidates} orphaned managed folders (no video files) ·{" "}
        {unmatchedManagedCandidates} unmatched managed folders ·{" "}
        {unmanagedShadowVideoFiles} unmanaged shadow video files
      </Text>
      {duplicateCandidates > 0 ? (
        <Text size="xs" c="dimmed" mt={4}>
          Duplicate groups below include every detected path so you can choose exactly what to keep.
        </Text>
      ) : null}
      {hasDiscoveryWarnings && (
        <DiscoveryWarningsSections
          excludedCandidates={excludedCandidates}
          duplicateCandidates={duplicateCandidates}
          orphanedManagedCandidates={orphanedManagedCandidates}
          unmatchedManagedCandidates={unmatchedManagedCandidates}
          unmanagedShadowVideoFiles={unmanagedShadowVideoFiles}
          excludedItems={excludedItems}
          duplicateItems={duplicateItems}
          orphanedItems={orphanedItems}
          unmatchedItems={unmatchedItems}
          unmanagedShadowItems={unmanagedShadowItems}
          busyIgnorePath={busyIgnorePath}
          busyOrphanPath={busyOrphanPath}
          busyImportPath={busyImportPath}
          importInFlightByPath={importInFlightByPath}
          importErrorsByPath={importErrorsByPath}
          importStatusByPath={importStatusByPath}
          ignoreStatusByPath={ignoreStatusByPath}
          rowErrors={rowErrors}
          renderIgnoreAction={renderIgnoreAction}
          handleOpenFolder={handleOpenFolder}
          handleRecycleOrphan={handleRecycleOrphan}
          handleImportUnmatched={handleImportUnmatched}
          setImportErrorDialogPath={(path) => setImportErrorDialogPath(path)}
          setHoveredRowKey={setHoveredRowKey}
          warningRowStyle={warningRowStyle}
        />
      )}
      <ImportErrorModal
        opened={importErrorDialogPath !== null}
        path={importErrorDialogPath}
        errorMessage={importDialogError}
        busyImportPath={busyImportPath}
        onClose={() => setImportErrorDialogPath(null)}
        onRetry={() => {
          if (importErrorDialogPath) {
            void handleImportUnmatched(importErrorDialogPath);
          }
        }}
      />
      <UnmatchedResolveModal
        opened={resolveDialogPath !== null}
        path={resolveDialogPath}
        loading={resolveLoading}
        busyImportPath={busyImportPath}
        candidatesPayload={resolveCandidates}
        selectedMovieId={selectedResolveMovieId}
        onChangeSelectedMovieId={setSelectedResolveMovieId}
        forceTakeover={resolveForceTakeover}
        onChangeForceTakeover={setResolveForceTakeover}
        error={resolveError}
        onCancel={() => setResolveDialogPath(null)}
        onConfirm={() => void handleResolveAndImportUnmatched()}
      />
      <DirectoryPickerModal
        opened={browsePath !== null}
        title="Browse orphaned managed folder"
        roots={browseRoots}
        initialPath={browsePath ?? ""}
        onClose={() => setBrowsePath(null)}
        mode="browse"
      />
    </Card>
  );
}
