import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconBan,
  IconFolderOpen,
  IconTrash,
} from "@tabler/icons-react";
import { useMemo, useState } from "react";
import {
  getConfig,
  getDiscoveryWarnings,
  getFsRoots,
  recycleOrphanedManagedFolder,
  runMaintenanceReconcile,
  saveConfig,
  waitForJobCompletion,
} from "../../api/client";
import DuplicateWarningGroup from "./DuplicateWarningGroup";
import UnmatchedWarningsSection from "./UnmatchedWarningsSection";
import WarningPathRow from "./WarningPathRow";
import DirectoryPickerModal from "../DirectoryPickerModal";

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
    setBusyImportPath(path);
    setImportInFlightByPath((current) => ({ ...current, [path]: true }));
    setImportStatusByPath((current) => ({
      ...current,
      [path]: { color: "blue", message: "Queueing import in Radarr..." },
    }));
    setImportErrorsByPath((current) => ({ ...current, [path]: "" }));
    try {
      const queued = await runMaintenanceReconcile({ path });
      setImportStatusByPath((current) => ({
        ...current,
        [path]: { color: "blue", message: `Import queued (job ${queued.job_id.slice(0, 8)}...)` },
      }));
      setImportErrorDialogPath((current) => (current === path ? null : current));

      void (async () => {
        try {
          await waitForJobCompletion(queued.job_id, { timeoutMs: 180000, pollIntervalMs: 1500 });
          setImportStatusByPath((current) => ({
            ...current,
            [path]: { color: "green", message: "Import finished successfully." },
          }));
          setImportErrorsByPath((current) => ({ ...current, [path]: "" }));
          await onRefreshWarnings();
        } catch (error) {
          const message = parseApiErrorMessage(error, "Import failed after being queued.");
          setImportErrorsByPath((current) => ({ ...current, [path]: message }));
          setImportStatusByPath((current) => ({
            ...current,
            [path]: { color: "red", message },
          }));
          setImportErrorDialogPath(path);
        } finally {
          setImportInFlightByPath((current) => ({ ...current, [path]: false }));
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
      setImportErrorsByPath((current) => ({ ...current, [path]: message }));
      setImportStatusByPath((current) => ({
        ...current,
        [path]: { color: "red", message },
      }));
      setImportErrorDialogPath(path);
    } finally {
      setBusyImportPath((current) => (current === path ? null : current));
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
        <Stack gap="sm" mt="xs">
            {excludedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Excluded Candidates ({excludedCandidates})</Text>
                {excludedItems.map((item) => (
                  <WarningPathRow
                    key={`excluded-${item.path}`}
                    rowKey={`excluded-${item.path}`}
                    label={`⚠ ${item.path}`}
                    onHover={setHoveredRowKey}
                    rowStyle={warningRowStyle}
                    actions={
                      <>
                        {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                        {renderIgnoreAction(item.path, "Keep ignored (add to paths.exclude_paths)")}
                      </>
                    }
                    status={ignoreStatusByPath[item.path]}
                  />
                ))}
              </Stack>
            )}
            {duplicateCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Potential Duplicates ({duplicateCandidates})</Text>
                {duplicateItems.map((item) => (
                  <DuplicateWarningGroup
                    key={`duplicate-${item.primary_path}`}
                    item={item}
                    onHover={setHoveredRowKey}
                    rowStyle={warningRowStyle}
                    makeActions={(path) => (
                      <>
                        {busyIgnorePath === path ? <Loader size="xs" /> : null}
                        {renderIgnoreAction(path, "Ignore this folder path")}
                      </>
                    )}
                    statusByPath={ignoreStatusByPath}
                  />
                ))}
              </Stack>
            )}
            {orphanedManagedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  Orphaned Managed Folders (no video files) ({orphanedManagedCandidates})
                </Text>
                {orphanedItems.map((item) => (
                  <WarningPathRow
                    key={`orphaned-${item.path}`}
                    rowKey={`orphaned-${item.path}`}
                    label={`⚠ ${item.path}`}
                    onHover={setHoveredRowKey}
                    rowStyle={warningRowStyle}
                    actions={
                      <>
                        {busyOrphanPath === item.path ? <Loader size="xs" /> : null}
                        {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                        {renderIgnoreAction(item.path, "Ignore this folder path")}
                        <Tooltip label="Browse folder" withArrow>
                          <ActionIcon
                            size="sm"
                            variant="light"
                            onClick={() => void handleOpenFolder(item.path)}
                            disabled={busyOrphanPath === item.path}
                            aria-label="Browse orphaned folder"
                          >
                            <IconFolderOpen size={14} />
                          </ActionIcon>
                        </Tooltip>
                        <Tooltip label="Recycle orphaned folder" withArrow>
                          <ActionIcon
                            size="sm"
                            color="red"
                            variant="light"
                            onClick={() => void handleRecycleOrphan(item.path)}
                            disabled={busyOrphanPath === item.path}
                            aria-label="Recycle orphaned folder"
                          >
                            <IconTrash size={14} />
                          </ActionIcon>
                        </Tooltip>
                      </>
                    }
                    status={ignoreStatusByPath[item.path]}
                  />
                ))}
                {orphanedItems.map((item) => {
                  const rowError = rowErrors[item.path];
                  if (!rowError) {
                    return null;
                  }
                  return (
                    <Text key={`orphaned-error-${item.path}`} size="xs" c="red">
                      {rowError}
                    </Text>
                  );
                })}
              </Stack>
            )}
            {unmanagedShadowVideoFiles > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  Unmanaged Shadow Video Files ({unmanagedShadowVideoFiles})
                </Text>
                {unmanagedShadowItems.map((item) => (
                  <WarningPathRow
                    key={`shadow-unmanaged-${item.path}`}
                    rowKey={`shadow-unmanaged-${item.path}`}
                    label={`⚠ ${item.path}`}
                    onHover={setHoveredRowKey}
                    rowStyle={warningRowStyle}
                    actions={
                      <>
                        {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                        {renderIgnoreAction(item.path, "Ignore this file path")}
                      </>
                    }
                    status={ignoreStatusByPath[item.path]}
                  />
                ))}
              </Stack>
            )}
            <UnmatchedWarningsSection
              unmatchedManagedCandidates={unmatchedManagedCandidates}
              unmatchedItems={unmatchedItems}
              busyIgnorePath={busyIgnorePath}
              busyImportPath={busyImportPath}
              importInFlightByPath={importInFlightByPath}
              importErrorsByPath={importErrorsByPath}
              importStatusByPath={importStatusByPath}
              ignoreStatusByPath={ignoreStatusByPath}
              setImportErrorDialogPath={(path) => setImportErrorDialogPath(path)}
              handleImportUnmatched={handleImportUnmatched}
              renderIgnoreAction={renderIgnoreAction}
              onHover={setHoveredRowKey}
              rowStyle={warningRowStyle}
            />
          </Stack>
      )}
      <Modal
        opened={importErrorDialogPath !== null}
        onClose={() => setImportErrorDialogPath(null)}
        title="Import Error"
        centered
      >
        <Stack gap="sm">
          <Text size="sm" c="dimmed">
            {importErrorDialogPath}
          </Text>
          <Text size="sm">{importDialogError || "Import failed."}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setImportErrorDialogPath(null)}>
              Close
            </Button>
            <Button
              color="red"
              loading={
                importErrorDialogPath !== null && busyImportPath === importErrorDialogPath
              }
              onClick={() => {
                if (importErrorDialogPath) {
                  void handleImportUnmatched(importErrorDialogPath);
                }
              }}
            >
              Retry
            </Button>
          </Group>
        </Stack>
      </Modal>
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
