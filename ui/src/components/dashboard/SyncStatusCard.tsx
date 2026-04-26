import { Badge, Button, Card, Group, Stack, Text } from "@mantine/core";
import type { RuntimeStatusResponse } from "../../api/client";
import { formatAge } from "../dashboardFormatters";

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
