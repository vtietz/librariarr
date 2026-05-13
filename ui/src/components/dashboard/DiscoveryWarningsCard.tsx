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
import { IconAlertCircle, IconFolderOpen, IconTrash, IconUpload } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import {
  getDiscoveryWarnings,
  getFsRoots,
  recycleOrphanedManagedFolder,
  runMaintenanceReconcile,
} from "../../api/client";
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
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  const [importErrorsByPath, setImportErrorsByPath] = useState<Record<string, string>>({});
  const [hoveredRowKey, setHoveredRowKey] = useState<string | null>(null);
  const [importErrorDialogPath, setImportErrorDialogPath] = useState<string | null>(null);

  const warningRowStyle = (rowKey: string) => ({
    flex: 1,
    minWidth: 0,
    borderRadius: "6px",
    padding: "4px 6px",
    backgroundColor:
      hoveredRowKey === rowKey ? "var(--mantine-color-gray-1)" : "transparent",
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
    setImportErrorsByPath((current) => ({ ...current, [path]: "" }));
    try {
      await runMaintenanceReconcile({ path });
      setImportErrorDialogPath((current) => (current === path ? null : current));
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
      setImportErrorDialogPath(path);
    } finally {
      setBusyImportPath((current) => (current === path ? null : current));
    }
  };

  const importDialogError =
    importErrorDialogPath !== null ? importErrorsByPath[importErrorDialogPath] ?? "" : "";

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
      {hasDiscoveryWarnings && (
        <Stack gap="sm" mt="xs">
            {excludedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Excluded Candidates ({excludedCandidates})</Text>
                {excludedItems.map((item) => (
                  <Group
                    key={`excluded-${item.path}`}
                    gap="xs"
                    wrap="nowrap"
                    onMouseEnter={() => setHoveredRowKey(`excluded-${item.path}`)}
                    onMouseLeave={() => setHoveredRowKey(null)}
                    style={warningRowStyle(`excluded-${item.path}`)}
                  >
                    <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
                      ⚠ {item.path}
                    </Text>
                  </Group>
                ))}
              </Stack>
            )}
            {duplicateCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Potential Duplicates ({duplicateCandidates})</Text>
                {duplicateItems.map((item) => (
                  <Group
                    key={`duplicate-${item.primary_path}`}
                    gap="xs"
                    wrap="nowrap"
                    onMouseEnter={() => setHoveredRowKey(`duplicate-${item.primary_path}`)}
                    onMouseLeave={() => setHoveredRowKey(null)}
                    style={warningRowStyle(`duplicate-${item.primary_path}`)}
                  >
                    <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
                      ⚠ {item.movie_ref}: {item.primary_path}
                    </Text>
                  </Group>
                ))}
              </Stack>
            )}
            {orphanedManagedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  Orphaned Managed Folders (no video files) ({orphanedManagedCandidates})
                </Text>
                {orphanedItems.map((item) => (
                  <Group
                    key={`orphaned-${item.path}`}
                    gap="xs"
                    wrap="nowrap"
                    align="flex-start"
                    onMouseEnter={() => setHoveredRowKey(`orphaned-${item.path}`)}
                    onMouseLeave={() => setHoveredRowKey(null)}
                    style={warningRowStyle(`orphaned-${item.path}`)}
                  >
                    <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
                      ⚠ {item.path}
                    </Text>
                    {busyOrphanPath === item.path ? <Loader size="xs" /> : null}
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
                  </Group>
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
                  <Group
                    key={`shadow-unmanaged-${item.path}`}
                    gap="xs"
                    wrap="nowrap"
                    onMouseEnter={() => setHoveredRowKey(`shadow-unmanaged-${item.path}`)}
                    onMouseLeave={() => setHoveredRowKey(null)}
                    style={warningRowStyle(`shadow-unmanaged-${item.path}`)}
                  >
                    <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
                      ⚠ {item.path}
                    </Text>
                  </Group>
                ))}
              </Stack>
            )}
            {unmatchedManagedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  Unmatched Managed Folders ({unmatchedManagedCandidates})
                </Text>
                <Text size="xs" c="dimmed">
                  Usually this means the folder is not imported in Radarr yet.
                </Text>
                {unmatchedItems.map((item) => (
                  <Group
                    key={`unmatched-${item.path}`}
                    gap="xs"
                    wrap="nowrap"
                    align="flex-start"
                    onMouseEnter={() => setHoveredRowKey(`unmatched-${item.path}`)}
                    onMouseLeave={() => setHoveredRowKey(null)}
                    style={warningRowStyle(`unmatched-${item.path}`)}
                  >
                    <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
                      ⚠ {item.path}
                    </Text>
                    {busyImportPath === item.path ? <Loader size="xs" /> : null}
                    {importErrorsByPath[item.path] ? (
                      <Tooltip
                        label="Import failed. Click for details and retry."
                        withArrow
                      >
                        <ActionIcon
                          size="sm"
                          color="red"
                          variant="light"
                          onClick={() => setImportErrorDialogPath(item.path)}
                          disabled={busyImportPath === item.path}
                          aria-label="Show import error details"
                        >
                          <IconAlertCircle size={14} />
                        </ActionIcon>
                      </Tooltip>
                    ) : (
                      <Tooltip label="Trigger import to Radarr" withArrow>
                        <ActionIcon
                          size="sm"
                          color="blue"
                          variant="light"
                          onClick={() => void handleImportUnmatched(item.path)}
                          disabled={busyImportPath === item.path}
                          aria-label="Import unmatched folder"
                        >
                          <IconUpload size={14} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                ))}
              </Stack>
            )}
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
