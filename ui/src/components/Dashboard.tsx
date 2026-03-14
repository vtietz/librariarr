import { Badge, Card, Group, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { getDiscoveryWarnings } from "../api/client";
import type { JobsSummary, RuntimeStatusResponse } from "../api/client";

type Status = "idle" | "ok" | "warning" | "disabled";

type Props = {
  radarrStatus: Status;
  sonarrStatus: Status;
  hasUnsavedChanges: boolean;
  lastDryRunSummary: string;
  runtimeStatus: RuntimeStatusResponse | null;
  jobsSummary: JobsSummary | null;
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
  runtimeStatus,
  jobsSummary
}: Props) {
  const [discoveryWarnings, setDiscoveryWarnings] = useState<Awaited<
    ReturnType<typeof getDiscoveryWarnings>
  > | null>(null);

  useEffect(() => {
    let active = true;

    const loadWarnings = async () => {
      try {
        const payload = await getDiscoveryWarnings({ limit: 10 });
        if (active) {
          setDiscoveryWarnings(payload);
        }
      } catch {
        if (active) {
          setDiscoveryWarnings(null);
        }
      }
    };

    void loadWarnings();
    const interval = window.setInterval(() => {
      void loadWarnings();
    }, 5000);

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
  const pendingIngest =
    runtimeStatus?.current_task.pending_ingest_dirs ??
    runtimeStatus?.last_reconcile?.pending_ingest_dirs ??
    0;
  const queuedChanges = runtimeStatus?.dirty_paths_queued ?? 0;
  const totalQueue = queuedChanges + pendingIngest;
  const activeJobs = jobsSummary?.active ?? 0;
  const latestFinishedJob = jobsSummary?.latest_finished;
  const jobsBadgeColor = activeJobs > 0 ? "blue" : "gray";

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
      <SimpleGrid cols={{ base: 1, md: 3 }}>
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
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Background Jobs</Text>
            <Badge color={jobsBadgeColor}>{activeJobs} active</Badge>
          </Group>
          <Text size="sm" c="dimmed" mt="xs">
            queued={jobsSummary?.queued ?? 0} · running={jobsSummary?.running ?? 0} · failed={jobsSummary?.failed ?? 0}
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Latest: {latestFinishedJob?.kind ?? "none"} · {latestFinishedJob?.status ?? "n/a"}
          </Text>
        </Card>
      </SimpleGrid>
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
          <Stack gap={4} mt="xs">
            {discoveryWarnings?.excluded_movie_candidates.slice(0, 3).map((item) => (
              <Text key={`excluded-${item.path}`} size="xs" c="dimmed">
                ⚠ excluded: {item.path}
              </Text>
            ))}
            {discoveryWarnings?.duplicate_movie_candidates.slice(0, 3).map((item) => (
              <Text key={`duplicate-${item.primary_path}`} size="xs" c="dimmed">
                ⚠ duplicate key {item.movie_ref}: {item.primary_path}
              </Text>
            ))}
          </Stack>
        )}
      </Card>
      <Card withBorder>
        <Text fw={600}>Last Dry-Run</Text>
        <Text c="dimmed" size="sm">
          {lastDryRunSummary || "No dry-run executed yet."}
        </Text>
      </Card>
    </Stack>
  );
}
