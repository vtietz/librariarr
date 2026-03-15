import { Badge, Button, Card, Group, Loader, ScrollArea, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { cancelJob, getDiscoveryWarnings, getJobs, runMaintenanceReconcile } from "../api/client";
import type { JobRecord, JobsSummary, RuntimeStatusResponse } from "../api/client";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
  jobsSummary: JobsSummary | null;
  runtimePollLatencyMs: number | null;
};

export default function Dashboard({
  hasUnsavedChanges,
  runtimeStatus,
  jobsSummary,
  runtimePollLatencyMs
}: Props) {
  const [discoveryWarnings, setDiscoveryWarnings] = useState<Awaited<
    ReturnType<typeof getDiscoveryWarnings>
  > | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobRecord[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [cancelingJobId, setCancelingJobId] = useState<string | null>(null);
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

  useEffect(() => {
    let active = true;
    let inFlight = false;

    const loadJobs = async () => {
      if (inFlight) {
        return;
      }
      inFlight = true;
      setLoadingJobs(true);
      try {
        const items = await getJobs({ limit: 12 });
        if (active) {
          setRecentJobs(items);
        }
      } catch {
        // Keep last known jobs to avoid table clearing during brief API timeouts.
      } finally {
        if (active) {
          setLoadingJobs(false);
        }
        inFlight = false;
      }
    };

    void loadJobs();
    const interval = window.setInterval(() => {
      void loadJobs();
    }, 3000);

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
  const knownLinksInMemory =
    runtimeStatus?.known_links_in_memory ?? runtimeStatus?.mapped_cache?.entries_total ?? 0;
  const pendingTasks = runtimeStatus?.pending_tasks ?? [];

  const formatAge = (timestamp: number | null | undefined) => {
    if (typeof timestamp !== "number") {
      return "-";
    }
    const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
    if (seconds < 60) {
      return `${seconds}s ago`;
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
      return `${minutes}m ago`;
    }
    const hours = Math.floor(minutes / 60);
    return `${hours}h ago`;
  };

  const formatDuration = (job: JobRecord) => {
    if (typeof job.started_at !== "number") {
      return "-";
    }
    const end = typeof job.finished_at === "number" ? job.finished_at : Date.now() / 1000;
    return `${Math.max(0, (end - job.started_at)).toFixed(1)}s`;
  };

  const badgeForJob = (job: JobRecord) => {
    if (job.status === "succeeded") {
      return "green";
    }
    if (job.status === "failed") {
      return "red";
    }
    if (job.status === "canceled") {
      return "gray";
    }
    if (job.status === "running") {
      return "blue";
    }
    return "yellow";
  };

  const canCancel = (job: JobRecord) => job.status === "queued" || job.status === "running";

  const formatTaskDuration = (task: {
    duration_seconds?: number | null;
    started_at?: number | null;
  }) => {
    if (typeof task.duration_seconds === "number") {
      return `${task.duration_seconds.toFixed(1)}s`;
    }
    if (typeof task.started_at === "number") {
      const now = Date.now() / 1000;
      return `${Math.max(0, now - task.started_at).toFixed(1)}s`;
    }
    return "-";
  };

  const formatTaskQueuedAt = (task: { queued_at?: number | null; next_run_at?: number | null }) => {
    if (typeof task.queued_at === "number") {
      return formatAge(task.queued_at);
    }
    if (typeof task.next_run_at === "number") {
      const dueIn = Math.max(0, Math.round(task.next_run_at - Date.now() / 1000));
      return `in ${dueIn}s`;
    }
    return "-";
  };

  const badgeForTask = (status: string) => {
    if (status === "running") {
      return "blue";
    }
    if (status === "queued") {
      return "yellow";
    }
    return "gray";
  };

  const handleCancel = async (jobId: string) => {
    setCancelingJobId(jobId);
    try {
      await cancelJob(jobId);
      const items = await getJobs({ limit: 12 });
      setRecentJobs(items);
    } catch (error) {
      console.error("[Dashboard] Failed to cancel job", jobId, error);
    } finally {
      setCancelingJobId(null);
    }
  };

  const handleRunReconcile = async () => {
    setRunningReconcile(true);
    try {
      await runMaintenanceReconcile();
      const items = await getJobs({ limit: 12 });
      setRecentJobs(items);
    } catch (error) {
      console.error("[Dashboard] Failed to queue maintenance reconcile", error);
    } finally {
      setRunningReconcile(false);
    }
  };

  return (
    <Stack>
      <Title order={3}>Dashboard</Title>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
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
        <Card withBorder>
          <Text fw={600}>Discovery Warnings</Text>
          <Text size="sm" c="dimmed">
            {excludedCandidates} excluded · {duplicateCandidates} duplicates
          </Text>
        </Card>
      </SimpleGrid>
      <SimpleGrid cols={{ base: 1, md: 4 }}>
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
          <Text fw={600}>Known Links (Memory)</Text>
          <Text size="sm" c="dimmed">
            {knownLinksInMemory} links currently indexed
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            mapped cache {runtimeStatus?.mapped_cache?.building ? "rebuilding" : "ready"}
          </Text>
        </Card>
        <Card withBorder>
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
        <Card withBorder>
          <Text fw={600}>Task List</Text>
          <Text size="sm" c="dimmed">
            {pendingTasks.length} pending/running tasks
          </Text>
          {pendingTasks.length === 0 ? (
            <Text size="xs" c="dimmed" mt="xs">No active tasks.</Text>
          ) : (
            <ScrollArea mt="xs" type="auto" scrollbars="y">
              <Table striped highlightOnHover withTableBorder withColumnBorders>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Name</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Source</Table.Th>
                    <Table.Th>Queued</Table.Th>
                    <Table.Th>Duration</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {pendingTasks.slice(0, 8).map((task) => (
                    <Table.Tr key={task.id}>
                      <Table.Td>
                        <Text size="xs" c="dimmed" lineClamp={1}>{task.name}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge color={badgeForTask(task.status)}>{task.status}</Badge>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed" lineClamp={1}>{task.source}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">{formatTaskQueuedAt(task)}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">{formatTaskDuration(task)}</Text>
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </ScrollArea>
          )}
        </Card>
      </SimpleGrid>
      <Card withBorder>
        <Text fw={600}>Operation Latency</Text>
        <Text size="sm" c="dimmed" mt="xs">
          Runtime status poll: {runtimePollLatencyMs ?? "-"} ms
        </Text>
        <Text size="sm" c="dimmed" mt="xs">
          Mapped cache rebuild: {runtimeStatus?.mapped_cache?.last_build_duration_ms ?? "-"} ms
        </Text>
        <Text size="sm" c="dimmed" mt="xs">
          Discovery cache rebuild: {runtimeStatus?.discovery_cache?.last_build_duration_ms ?? "-"} ms
        </Text>
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
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Recent Jobs</Text>
          {loadingJobs ? <Loader size="xs" /> : <Text size="xs" c="dimmed">live</Text>}
        </Group>
        {recentJobs.length === 0 ? (
          <Text size="sm" c="dimmed">
            No jobs yet.
          </Text>
        ) : (
          <ScrollArea>
            <Table highlightOnHover withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Type</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Queued</Table.Th>
                  <Table.Th>Duration</Table.Th>
                  <Table.Th>Error</Table.Th>
                  <Table.Th>Action</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {recentJobs.map((job) => (
                  <Table.Tr key={job.job_id}>
                    <Table.Td>{job.kind}</Table.Td>
                    <Table.Td>
                      <Badge color={badgeForJob(job)}>{job.status}</Badge>
                    </Table.Td>
                    <Table.Td>{formatAge(job.queued_at)}</Table.Td>
                    <Table.Td>{formatDuration(job)}</Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed" lineClamp={1}>
                        {job.error ?? "-"}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      {canCancel(job) ? (
                        <Button
                          size="compact-xs"
                          color="red"
                          variant="light"
                          loading={cancelingJobId === job.job_id}
                          disabled={Boolean(job.cancel_requested)}
                          onClick={() => void handleCancel(job.job_id)}
                        >
                          {job.cancel_requested ? "Cancel Requested" : "Cancel"}
                        </Button>
                      ) : (
                        <Text size="xs" c="dimmed">-</Text>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Card>
    </Stack>
  );
}
