import { Badge, Button, Card, Group, ScrollArea, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { getDiscoveryWarnings, runMaintenanceReconcile } from "../api/client";
import type { JobsSummary, RuntimeStatusResponse } from "../api/client";
import {
  badgeForTask,
  formatAge,
  formatCoverage,
  formatSigned,
  formatTaskDuration,
  formatTaskQueuedAt,
} from "./dashboardFormatters";
import { useUnmatchedDelta } from "./useUnmatchedDelta";

type Props = { hasUnsavedChanges: boolean; runtimeStatus: RuntimeStatusResponse | null; jobsSummary: JobsSummary | null };

export default function Dashboard({
  hasUnsavedChanges,
  runtimeStatus,
  jobsSummary
}: Props) {
  const [discoveryWarnings, setDiscoveryWarnings] = useState<Awaited<
    ReturnType<typeof getDiscoveryWarnings>
  > | null>(null);
  const [runningReconcile, setRunningReconcile] = useState(false);

  useEffect(() => {
    let active = true;
    let inFlight = false;

    const loadWarnings = async () => {
      if (inFlight) {
        return;
      }
      inFlight = true;
      try {
        const payload = await getDiscoveryWarnings({ limit: 10 });
        if (active) {
          setDiscoveryWarnings(payload);
        }
      } catch {
        // Keep last known snapshot to avoid flashing empty state on transient failures.
      } finally {
        inFlight = false;
      }
    };

    void loadWarnings();
    const interval = window.setInterval(() => {
      void loadWarnings();
    }, 7000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const excludedCandidates = discoveryWarnings?.summary.excluded_movie_candidates ?? 0;
  const duplicateCandidates = discoveryWarnings?.summary.duplicate_movie_candidates ?? 0;
  const hasDiscoveryWarnings = excludedCandidates > 0 || duplicateCandidates > 0;

  const taskState = runtimeStatus?.current_task.state ?? "idle";
  const taskBadgeColor =
    taskState === "running" ? "blue" : taskState === "error" ? "red" : "gray";
  const queuedChanges = runtimeStatus?.dirty_paths_queued ?? 0;
  const totalQueue = queuedChanges;
  const activeJobs = jobsSummary?.active ?? 0;
  const jobsBadgeColor = activeJobs > 0 ? "blue" : "gray";
  const knownLinksInMemory =
    runtimeStatus?.known_links_in_memory ?? runtimeStatus?.mapped_cache?.entries_total ?? 0;
  const mappedEntriesTotal = runtimeStatus?.mapped_cache?.entries_total ?? knownLinksInMemory;
  const lastMatchedMovies = runtimeStatus?.last_reconcile?.matched_movies;
  const lastUnmatchedMovies = runtimeStatus?.last_reconcile?.unmatched_movies;
  const lastMatchedSeries = runtimeStatus?.last_reconcile?.matched_series;
  const lastUnmatchedSeries = runtimeStatus?.last_reconcile?.unmatched_series;
  const lastCreatedLinks = runtimeStatus?.last_reconcile?.created_links ?? 0;
  const movieCountKnown =
    typeof lastMatchedMovies === "number" || typeof lastUnmatchedMovies === "number";
  const seriesCountKnown =
    typeof lastMatchedSeries === "number" || typeof lastUnmatchedSeries === "number";

  const movieCoverage = formatCoverage(lastMatchedMovies, lastUnmatchedMovies);
  const seriesCoverage = formatCoverage(lastMatchedSeries, lastUnmatchedSeries);
  const unmatchedDelta = useUnmatchedDelta({
    finishedAt: runtimeStatus?.last_reconcile?.finished_at,
    unmatchedMovies: lastUnmatchedMovies,
    unmatchedSeries: lastUnmatchedSeries,
  });
  const healthStatus = runtimeStatus?.health?.status ?? "starting";
  const healthBadgeColor =
    healthStatus === "ok" ? "green" : healthStatus === "degraded" ? "yellow" : "gray";
  const primaryHealthReason = runtimeStatus?.health?.reasons?.[0] ?? "Waiting for snapshot";

  const handleRunReconcile = async () => {
    setRunningReconcile(true);
    try {
      await runMaintenanceReconcile();
    } catch (error) {
      console.error("[Dashboard] Failed to queue maintenance reconcile", error);
    } finally {
      setRunningReconcile(false);
    }
  };

  type DashboardTaskStatus = "idle" | "queued" | "running" | "error";
  type TaskSlot = {
    id: string;
    name: string;
    source: string;
    status: DashboardTaskStatus;
    detail: string;
    queuedAt: string;
    duration: string;
  };

  const pendingTasks = runtimeStatus?.pending_tasks ?? [];
  const consumedTaskIds = new Set<string>();
  const findPendingTask = (predicate: (task: (typeof pendingTasks)[number]) => boolean) => {
    const task = pendingTasks.find(predicate);
    if (task) {
      consumedTaskIds.add(task.id);
    }
    return task;
  };

  const filesystemTask = findPendingTask((task) => task.id === "filesystem-debounce");
  const manualReconcileTask = findPendingTask((task) => task.name.toLowerCase().includes("manual reconcile"));
  const mappedRefreshTask = findPendingTask((task) => task.name.toLowerCase().includes("refresh mapped"));
  const discoverySnapshotTask = findPendingTask((task) => task.name.toLowerCase().includes("discovery snapshot rebuild"));
  const reconcileCycleTask = findPendingTask((task) => task.name.toLowerCase().includes("reconcile cycle"));
  const runtimeTaskFromPending = findPendingTask((task) => task.source === "runtime-status");

  const buildReconcileScopeSummary = (metrics: { active_movie_root?: string | null; active_series_root?: string | null; movie_folders_seen?: number; series_folders_seen?: number; affected_paths_count?: number | null } | undefined | null) => {
    if (!metrics) {
      return null;
    }
    const hasMovieCount = typeof metrics.movie_folders_seen === "number";
    const hasSeriesCount = typeof metrics.series_folders_seen === "number";
    if (!hasMovieCount && !hasSeriesCount) {
      return null;
    }

    const modeText =
      typeof metrics.affected_paths_count === "number"
        ? `incremental (${metrics.affected_paths_count} affected paths)`
        : "full";
    const movieCount = hasMovieCount ? metrics.movie_folders_seen : 0;
    const seriesCount = hasSeriesCount ? metrics.series_folders_seen : 0;
    const movieRootText = metrics.active_movie_root ? ` · movie root ${metrics.active_movie_root}` : "";
    const seriesRootText = metrics.active_series_root
      ? ` · series root ${metrics.active_series_root}`
      : "";
    return `${modeText} · considered folders M/S ${movieCount}/${seriesCount}${movieRootText}${seriesRootText}`;
  };

  const runtimeLoopStatus: DashboardTaskStatus =
    taskState === "running" ? "running" : taskState === "error" ? "error" : "idle";
  const runningScopeSummary = buildReconcileScopeSummary(runtimeStatus?.current_task);
  const lastScopeSummary = buildReconcileScopeSummary(runtimeStatus?.last_reconcile);
  const runtimeLoopDetail =
    runtimeLoopStatus === "error"
      ? runtimeStatus?.current_task.error ??
        runtimeStatus?.last_reconcile?.error ??
        (lastScopeSummary
          ? `Last reconcile failed · ${lastScopeSummary}`
          : "Last reconcile failed (no message provided).")
      : runningScopeSummary ??
        runtimeStatus?.current_task.phase ??
        runtimeTaskFromPending?.detail ??
        "Waiting for debounce or manual trigger";
  const runtimeLoopQueuedAt =
    runtimeLoopStatus === "error"
      ? formatAge(runtimeStatus?.current_task.updated_at ?? runtimeStatus?.last_reconcile?.finished_at)
      : runtimeStatus?.current_task.started_at != null
        ? formatAge(runtimeStatus.current_task.started_at)
        : "-";

  const runtimeLoopSlot: TaskSlot = {
    id: "runtime-loop",
    name: "Runtime Reconcile Loop",
    source: "runtime-status",
    status: runtimeLoopStatus,
    detail: runtimeLoopDetail,
    queuedAt: runtimeLoopQueuedAt,
    duration: formatTaskDuration(runtimeStatus?.current_task ?? {}),
  };

  const filesystemDebounceSlot: TaskSlot = {
    id: "filesystem-debounce",
    name: "Filesystem Debounce",
    source: "filesystem",
    status: filesystemTask?.status ?? "idle",
    detail:
      filesystemTask?.detail ??
      `${queuedChanges} filesystem changes waiting for runtime reconcile`,
    queuedAt: filesystemTask ? formatTaskQueuedAt(filesystemTask) : "-",
    duration: filesystemTask ? formatTaskDuration(filesystemTask) : "-",
  };

  const manualReconcileSlot: TaskSlot = {
    id: "manual-reconcile",
    name: "Manual Reconcile Job",
    source: "job-manager",
    status: manualReconcileTask?.status ?? "idle",
    detail: manualReconcileTask?.detail ?? "On-demand full library reconcile",
    queuedAt: manualReconcileTask ? formatTaskQueuedAt(manualReconcileTask) : "-",
    duration: manualReconcileTask ? formatTaskDuration(manualReconcileTask) : "-",
  };

  const mappedCacheRefreshSlot: TaskSlot = {
    id: "mapped-cache-refresh",
    name: "Mapped Cache Refresh",
    source: "cache",
    status: runtimeStatus?.mapped_cache?.building
      ? "running"
      : mappedRefreshTask?.status ?? "idle",
    detail: runtimeStatus?.mapped_cache?.building
      ? "Rebuilding mapped directory index"
      : "Ready",
    queuedAt: mappedRefreshTask ? formatTaskQueuedAt(mappedRefreshTask) : "-",
    duration:
      typeof runtimeStatus?.mapped_cache?.last_build_duration_ms === "number"
        ? `${runtimeStatus.mapped_cache.last_build_duration_ms} ms`
        : mappedRefreshTask
          ? formatTaskDuration(mappedRefreshTask)
          : "-",
  };

  const discoveryCacheRefreshSlot: TaskSlot = {
    id: "discovery-cache-refresh",
    name: "Discovery Cache Refresh",
    source: "cache",
    status: runtimeStatus?.discovery_cache?.building ? "running" : "idle",
    detail: runtimeStatus?.discovery_cache?.building
      ? "Rebuilding discovery warnings snapshot"
      : "Ready",
    queuedAt: "-",
    duration:
      typeof runtimeStatus?.discovery_cache?.last_build_duration_ms === "number"
        ? `${runtimeStatus.discovery_cache.last_build_duration_ms} ms`
        : "-",
  };

  const discoverySnapshotRebuildSlot: TaskSlot = {
    id: "discovery-snapshot-rebuild", name: "Discovery Snapshot Rebuild", source: "cache",
    status: discoverySnapshotTask?.status ?? "idle", detail: discoverySnapshotTask?.detail ?? "Ready",
    queuedAt: discoverySnapshotTask ? formatTaskQueuedAt(discoverySnapshotTask) : "-",
    duration: discoverySnapshotTask ? formatTaskDuration(discoverySnapshotTask) : "-",
  };

  const reconcileCycleSlot: TaskSlot = {
    id: "reconcile-cycle", name: "Reconcile Cycle", source: "runtime", status: reconcileCycleTask?.status ?? "idle",
    detail: reconcileCycleTask?.detail ?? (lastScopeSummary ? `Last reconcile completed · ${lastScopeSummary}` : "Waiting for next reconcile cycle"),
    queuedAt: reconcileCycleTask ? formatTaskQueuedAt(reconcileCycleTask) : formatAge(runtimeStatus?.last_reconcile?.finished_at),
    duration: reconcileCycleTask
      ? formatTaskDuration(reconcileCycleTask)
      : typeof runtimeStatus?.last_reconcile?.duration_seconds === "number" ? `${runtimeStatus.last_reconcile.duration_seconds.toFixed(1)}s` : "-",
  };

  const uncategorizedTaskSlots: TaskSlot[] = pendingTasks
    .filter((task) => !consumedTaskIds.has(task.id))
    .map((task) => ({
      id: `uncategorized-${task.id}`,
      name: task.name || "Background Task",
      source: task.source || "task-manager",
      status: task.status === "queued" || task.status === "running" || task.status === "error" ? task.status : "idle",
      detail: task.detail || task.status,
      queuedAt: formatTaskQueuedAt(task),
      duration: formatTaskDuration(task),
    }));

  const taskSlots: TaskSlot[] = [
    runtimeLoopSlot,
    filesystemDebounceSlot,
    manualReconcileSlot,
    mappedCacheRefreshSlot,
    discoveryCacheRefreshSlot,
    discoverySnapshotRebuildSlot,
    reconcileCycleSlot,
    ...uncategorizedTaskSlots,
  ];

  const uncategorizedTaskCount = uncategorizedTaskSlots.length;

  return (
    <Stack gap="md">
      <Title order={3}>Dashboard</Title>
      <Text size="sm" c="dimmed">
        Live operations are split into two lanes: runtime loop (single reconcile worker) and job queue (manual/auxiliary jobs).
      </Text>

      <Text fw={600} size="sm" c="dimmed">System Status</Text>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
        <Card withBorder h={126}>
          <Group justify="space-between">
            <Text fw={600}>Config Draft</Text>
            <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
              {hasUnsavedChanges ? "unsaved changes" : "in sync"}
            </Badge>
          </Group>
          <Text c="dimmed" size="sm" mt="xs">
            UI draft and saved file consistency
          </Text>
        </Card>
        <Card withBorder h={126}>
          <Group justify="space-between">
            <Text fw={600}>System Health</Text>
            <Badge color={healthBadgeColor}>{healthStatus}</Badge>
          </Group>
          <Text c="dimmed" size="sm" mt="xs">
            {primaryHealthReason}
          </Text>
        </Card>
        <Card withBorder h={126}>
          <Group justify="space-between">
            <Text fw={600}>Runtime Loop</Text>
            <Badge color={taskBadgeColor}>{taskState}</Badge>
          </Group>
          <Text c="dimmed" size="sm" mt="xs">
            {runtimeStatus?.current_task.trigger_source ?? "waiting"}
            {runtimeStatus?.current_task.phase ? ` · ${runtimeStatus.current_task.phase}` : ""}
            {runtimeStatus?.current_task.active_movie_root
              ? ` · movie root ${runtimeStatus.current_task.active_movie_root}`
              : ""}
            {runtimeStatus?.current_task.active_series_root
              ? ` · series root ${runtimeStatus.current_task.active_series_root}`
              : ""}
          </Text>
        </Card>
        <Card withBorder h={126}>
          <Group justify="space-between">
            <Text fw={600}>Job Queue</Text>
            <Badge color={jobsBadgeColor}>{activeJobs} active</Badge>
          </Group>
          <Text size="sm" c="dimmed" mt="xs">
            queued={jobsSummary?.queued ?? 0} · running={jobsSummary?.running ?? 0}
            {` · failed=${jobsSummary?.failed ?? 0}`}
          </Text>
          <Text size="sm" c="dimmed" mt="xs">Manual reconcile and API-triggered maintenance jobs</Text>
        </Card>
      </SimpleGrid>

      <Text fw={600} size="sm" c="dimmed">Pipeline & Caches</Text>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
        <Card withBorder h={146}>
          <Text fw={600}>Filesystem Queue</Text>
          <Text size="sm" c="dimmed">
            {totalQueue} pending ({queuedChanges} fs changes)
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Next debounce run in {runtimeStatus?.next_event_reconcile_in_seconds ?? 0}s
          </Text>
        </Card>
        <Card withBorder h={146}>
          <Text fw={600}>Mapped Index Entries</Text>
          <Text size="sm" c="dimmed">
            {mappedEntriesTotal} mapped directories in cache
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            mapped cache {runtimeStatus?.mapped_cache?.building ? "rebuilding" : "ready"}
          </Text>
        </Card>
        <Card withBorder h={146}>
          <Group justify="space-between">
            <Text fw={600}>Last Reconcile</Text>
            <Button
              size="compact-xs"
              variant="light"
              loading={runningReconcile}
              onClick={() => void handleRunReconcile()}
            >
              Run Reconcile
            </Button>
          </Group>
          <Text size="sm" c="dimmed">
            {(runtimeStatus?.last_reconcile?.state ?? "none").toUpperCase()} ·
            {` duration ${runtimeStatus?.last_reconcile?.duration_seconds ?? 0}s`}
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            folders M/S {runtimeStatus?.last_reconcile?.movie_folders_seen ?? 0}/
            {runtimeStatus?.last_reconcile?.series_folders_seen ?? 0} · created links
            {` ${runtimeStatus?.last_reconcile?.created_links ?? 0}`}
          </Text>
        </Card>
        <Card withBorder h={146}>
          <Text fw={600}>Arr Match Snapshot</Text>
          <Text size="sm" c="dimmed">
            Movies {movieCoverage}
            {movieCountKnown
              ? ` · unmatched ${typeof lastUnmatchedMovies === "number" ? lastUnmatchedMovies : 0}`
              : " · unmatched n/a"}
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Series {seriesCoverage}
            {seriesCountKnown
              ? ` · unmatched ${typeof lastUnmatchedSeries === "number" ? lastUnmatchedSeries : 0}`
              : " · unmatched n/a"}
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Created links in last run: {lastCreatedLinks}
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Delta unmatched vs previous run M/S: {formatSigned(unmatchedDelta?.movies ?? null)}/
            {formatSigned(unmatchedDelta?.series ?? null)}
          </Text>
        </Card>
      </SimpleGrid>

      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Task Slots</Text>
          <Text size="xs" c="dimmed">
            {uncategorizedTaskCount > 0
              ? `${uncategorizedTaskCount} additional queued/running task(s) shown below`
              : "all active tasks mapped to slots"}
          </Text>
        </Group>
        <Text size="sm" c="dimmed" mb="sm">
          Runtime loop and background queue are shown with the same slot layout for faster scanning.
        </Text>
        <Table highlightOnHover withTableBorder withColumnBorders>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Task</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Source</Table.Th>
              <Table.Th>Detail</Table.Th>
              <Table.Th>Queued</Table.Th>
              <Table.Th>Duration</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {taskSlots.map((slot) => (
              <Table.Tr key={slot.id}>
                <Table.Td>{slot.name}</Table.Td>
                <Table.Td>
                  <Badge color={badgeForTask(slot.status)}>{slot.status}</Badge>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{slot.source}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed" lineClamp={2}>{slot.detail}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{slot.queuedAt}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{slot.duration}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>Discovery Warnings</Text>
          <Badge color={hasDiscoveryWarnings ? "yellow" : "green"}>
            {hasDiscoveryWarnings ? "attention" : "clear"}
          </Badge>
        </Group>
        <Text size="sm" c="dimmed" mt="xs">
          {excludedCandidates} excluded movie candidates · {duplicateCandidates} potential duplicates
        </Text>
        {hasDiscoveryWarnings && (
          <ScrollArea mt="xs" type="auto" scrollbars="y" h={160}>
            <Stack gap={4}>
              {discoveryWarnings?.excluded_movie_candidates.slice(0, 6).map((item) => (
                <Text key={`excluded-${item.path}`} size="xs" c="dimmed">
                  ⚠ excluded: {item.path}
                </Text>
              ))}
              {discoveryWarnings?.duplicate_movie_candidates.slice(0, 6).map((item) => (
                <Text key={`duplicate-${item.primary_path}`} size="xs" c="dimmed">
                  ⚠ duplicate key {item.movie_ref}: {item.primary_path}
                </Text>
              ))}
            </Stack>
          </ScrollArea>
        )}
      </Card>
    </Stack>
  );
}
