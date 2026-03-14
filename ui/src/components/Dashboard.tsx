import { Badge, Card, Group, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import type { RuntimeStatusResponse } from "../api/client";

type Status = "idle" | "ok" | "warning" | "disabled";

type Props = {
  radarrStatus: Status;
  sonarrStatus: Status;
  hasUnsavedChanges: boolean;
  lastDryRunSummary: string;
  runtimeStatus: RuntimeStatusResponse | null;
};

const toneByStatus: Record<Status, string> = {
  idle: "gray",
  ok: "green",
  warning: "yellow",
  disabled: "blue"
};

export default function Dashboard({
  radarrStatus,
  sonarrStatus,
  hasUnsavedChanges,
  lastDryRunSummary,
  runtimeStatus
}: Props) {
  const taskState = runtimeStatus?.current_task.state ?? "idle";
  const taskBadgeColor =
    taskState === "running" ? "blue" : taskState === "error" ? "red" : "gray";
  const pendingIngest =
    runtimeStatus?.current_task.pending_ingest_dirs ??
    runtimeStatus?.last_reconcile?.pending_ingest_dirs ??
    0;
  const queuedChanges = runtimeStatus?.dirty_paths_queued ?? 0;
  const totalQueue = queuedChanges + pendingIngest;

  return (
    <Stack>
      <Title order={3}>Dashboard</Title>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Radarr Diagnostics</Text>
            <Badge color={toneByStatus[radarrStatus]}>{radarrStatus}</Badge>
          </Group>
        </Card>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Sonarr Diagnostics</Text>
            <Badge color={toneByStatus[sonarrStatus]}>{sonarrStatus}</Badge>
          </Group>
        </Card>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Config Draft</Text>
            <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
              {hasUnsavedChanges ? "unsaved changes" : "in sync"}
            </Badge>
          </Group>
        </Card>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Runtime Task</Text>
            <Badge color={taskBadgeColor}>{taskState}</Badge>
          </Group>
          <Text c="dimmed" size="sm" mt="xs">
            {runtimeStatus?.current_task.trigger_source ?? "waiting"}
            {runtimeStatus?.current_task.phase ? ` · ${runtimeStatus.current_task.phase}` : ""}
          </Text>
        </Card>
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder>
          <Text fw={600}>Queue</Text>
          <Text size="sm" c="dimmed">
            {totalQueue} pending ({queuedChanges} fs changes, {pendingIngest} ingest candidates)
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Next debounce run in {runtimeStatus?.next_event_reconcile_in_seconds ?? 0}s
          </Text>
        </Card>
        <Card withBorder>
          <Text fw={600}>Last Reconcile</Text>
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
      </SimpleGrid>
      <Card withBorder>
        <Text fw={600}>Last Dry-Run</Text>
        <Text c="dimmed" size="sm">
          {lastDryRunSummary || "No dry-run executed yet."}
        </Text>
      </Card>
    </Stack>
  );
}
