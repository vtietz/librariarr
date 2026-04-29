import { Badge, Button, Card, Group, Loader, Stack, Text } from "@mantine/core";
import type { RuntimeStatusResponse } from "../../api/client";
import { formatAge, formatElapsed } from "../dashboardFormatters";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
  runningReconcile: boolean;
  onRunFullReconcile: () => Promise<void>;
};

function healthBadgeColor(status: string): string {
  if (status === "ok") {
    return "green";
  }
  if (status === "degraded") {
    return "yellow";
  }
  return "gray";
}

function stateBadgeColor(state: string): string {
  if (state === "running") {
    return "blue";
  }
  if (state === "error") {
    return "red";
  }
  return "gray";
}

function phaseLabel(phase: string | null | undefined): string {
  switch (phase) {
    case "reconcile":
      return "Starting…";
    case "startup_full_reconcile":
      return "Starting…";
    case "running":
      return "Running…";
    case "inventory_fetched":
      return "Fetched inventory…";
    case "scope_resolved":
      return "Resolving scope…";
    case "planning_movies":
      return "Planning movie projection…";
    case "planning_series":
      return "Planning series projection…";
    case "auto_add_movies":
      return "Resolving unmatched movies…";
    case "auto_add_series":
      return "Resolving unmatched series…";
    case "indexed":
      return "Projecting…";
    case "applied":
      return "Applying…";
    case "cleaned":
      return "Cleaning up…";
    case "completed":
      return "Finishing…";
    default:
      return "Working…";
  }
}

function buildProgressText(
  task: RuntimeStatusResponse["current_task"],
): string | null {
  if (task.state !== "running") return null;

  const parts: string[] = [phaseLabel(task.phase)];

  const moviesSeen = task.movie_folders_seen ?? 0;
  const seriesSeen = task.series_folders_seen ?? 0;
  if (moviesSeen > 0 || seriesSeen > 0) {
    const items: string[] = [];
    if (moviesSeen > 0) items.push(`${moviesSeen} movies`);
    if (seriesSeen > 0) items.push(`${seriesSeen} series`);
    parts.push(items.join(", "));
  }

  const links = task.created_links ?? 0;
  if (links > 0) parts.push(`${links} links`);

  if (task.active_movie_root) {
    parts.push(`root ${task.active_movie_root}`);
  }
  if (task.active_series_root) {
    parts.push(`series root ${task.active_series_root}`);
  }

  const movieProcessed = task.movie_items_processed ?? 0;
  const movieTotal = task.movie_items_total ?? 0;
  const seriesProcessed = task.series_items_processed ?? 0;
  const seriesTotal = task.series_items_total ?? 0;
  const progressCounters: string[] = [];
  if (movieTotal > 0) {
    progressCounters.push(`${movieProcessed}/${movieTotal} movies processed`);
  }
  if (seriesTotal > 0) {
    progressCounters.push(`${seriesProcessed}/${seriesTotal} series processed`);
  }
  if (progressCounters.length > 0) {
    parts.push(progressCounters.join(", "));
  }

  if (task.started_at) {
    parts.push(formatElapsed(task.started_at));
  }

  return parts.join(" · ");
}

function buildLastSyncText(
  lastReconcile: RuntimeStatusResponse["last_reconcile"],
): string {
  if (!lastReconcile?.finished_at) {
    return "No completed sync yet";
  }

  const parts = [`Last sync ${formatAge(lastReconcile.finished_at)}`];

  if (typeof lastReconcile.duration_seconds === "number") {
    parts.push(`${lastReconcile.duration_seconds.toFixed(1)}s`);
  }

  const createdLinks = lastReconcile.created_links ?? 0;
  if (createdLinks > 0) {
    parts.push(`${createdLinks} links created`);
  }

  const stats = lastReconcile.full_reconcile_stats;
  if (stats) {
    const projected = stats.total_projected_files;
    if (typeof projected === "number") {
      parts.push(`${projected} files projected`);
    }
    const autoAdded =
      Number(stats.auto_added_movies ?? 0) + Number(stats.auto_added_series ?? 0);
    if (autoAdded > 0) {
      parts.push(`${autoAdded} auto-added`);
    }
    const ingested = Number(stats.ingested_movies ?? 0);
    if (ingested > 0) {
      parts.push(`${ingested} ingested`);
    }
  }

  return parts.join(" · ");
}

export default function SyncStatusCard({
  hasUnsavedChanges,
  runtimeStatus,
  runningReconcile,
  onRunFullReconcile,
}: Props) {
  const healthStatus = runtimeStatus?.health?.status ?? "starting";
  const healthReason = runtimeStatus?.health?.reasons?.[0] ?? "Waiting for status";
  const taskState = runtimeStatus?.current_task.state ?? "idle";
  const lastSyncText = buildLastSyncText(runtimeStatus?.last_reconcile ?? null);
  const progressText = buildProgressText(
    runtimeStatus?.current_task ?? { state: "idle", phase: null, trigger_source: null, started_at: null, updated_at: null, error: null },
  );

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Sync Status</Text>
        <Group gap="xs">
          <Badge color={healthBadgeColor(healthStatus)} size="sm">
            {healthStatus}
          </Badge>
          <Badge
            color={hasUnsavedChanges ? "yellow" : "green"}
            size="sm"
            variant="light"
          >
            {hasUnsavedChanges ? "config unsaved" : "config synced"}
          </Badge>
          <Badge color={stateBadgeColor(taskState)} size="sm">
            {taskState}
          </Badge>
        </Group>
      </Group>
      <Stack gap={4}>
        <Text size="sm" c="dimmed">
          {healthReason}
        </Text>
        {progressText && (
          <Group gap="xs">
            <Loader size={12} />
            <Text size="xs" c="blue">
              {progressText}
            </Text>
          </Group>
        )}
        <Group justify="space-between" align="center">
          <Text size="xs" c="dimmed">
            {lastSyncText}
          </Text>
          <Button
            size="compact-xs"
            variant="light"
            loading={runningReconcile}
            onClick={() => void onRunFullReconcile()}
          >
            Run Full Reconcile
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
