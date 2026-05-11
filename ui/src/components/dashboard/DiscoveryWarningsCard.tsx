import {
  ActionIcon,
  Badge,
  Card,
  Group,
  Loader,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconFolderOpen, IconTrash } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import {
  getDiscoveryWarnings,
  getFsRoots,
  recycleOrphanedManagedFolder,
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
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

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
                  <Text key={`excluded-${item.path}`} size="xs" c="dimmed">
                    ⚠ {item.path}
                  </Text>
                ))}
              </Stack>
            )}
            {duplicateCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Potential Duplicates ({duplicateCandidates})</Text>
                {duplicateItems.map((item) => (
                  <Text key={`duplicate-${item.primary_path}`} size="xs" c="dimmed">
                    ⚠ {item.movie_ref}: {item.primary_path}
                  </Text>
                ))}
              </Stack>
            )}
            {orphanedManagedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  Orphaned Managed Folders (no video files) ({orphanedManagedCandidates})
                </Text>
                {orphanedItems.map((item) => (
                  <Group key={`orphaned-${item.path}`} gap="xs" wrap="nowrap" align="flex-start">
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
                  <Text key={`shadow-unmanaged-${item.path}`} size="xs" c="dimmed">
                    ⚠ {item.path}
                  </Text>
                ))}
              </Stack>
            )}
            {unmatchedManagedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>
                  Unmatched Managed Folders ({unmatchedManagedCandidates})
                </Text>
                {unmatchedItems.map((item) => (
                  <Text key={`unmatched-${item.path}`} size="xs" c="dimmed">
                    ⚠ {item.path}
                  </Text>
                ))}
              </Stack>
            )}
          </Stack>
      )}
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
