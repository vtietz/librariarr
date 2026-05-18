import { Badge, Button, Card, Group, Loader, ScrollArea, Stack, Table, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  cancelJob,
  clearCompletedJobs,
  deleteJob,
  getJobs,
  getJobsSummary,
  type JobRecord,
  type JobsSummary,
} from "../api/client";
import { formatDurationSeconds } from "./dashboardFormatters";

type Status = JobRecord["status"];

const TERMINAL_STATUSES = new Set<Status>(["succeeded", "failed", "canceled"]);

function statusColor(status: Status): string {
  switch (status) {
    case "queued":
      return "yellow";
    case "running":
      return "blue";
    case "succeeded":
      return "green";
    case "failed":
      return "red";
    case "canceled":
      return "gray";
    default:
      return "dark";
  }
}

function formatTime(timestamp: number | null): string {
  if (typeof timestamp !== "number") {
    return "-";
  }
  return new Date(timestamp * 1000).toLocaleString();
}

function formatRuntime(job: JobRecord): string {
  if (typeof job.started_at !== "number") {
    return "-";
  }
  const end = typeof job.finished_at === "number" ? job.finished_at : Date.now() / 1000;
  return formatDurationSeconds(end - job.started_at);
}

export default function ActivityPanel() {
  const [summary, setSummary] = useState<JobsSummary | null>(null);
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actioning, setActioning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchJobsData = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError(null);
    try {
      const [summaryData, items] = await Promise.all([
        getJobsSummary({ includeHidden: true }),
        getJobs({ limit: 200, includeHidden: true }),
      ]);
      setSummary(summaryData);
      setJobs(items);
    } catch {
      setError("Failed to load activity.");
    } finally {
      if (mode === "initial") {
        setLoading(false);
      } else {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchJobsData("initial");
  }, [fetchJobsData]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      void fetchJobsData();
    }, 3000);

    return () => {
      window.clearInterval(interval);
    };
  }, [fetchJobsData]);

  const activeJobs = useMemo(
    () => jobs.filter((job) => job.status === "queued" || job.status === "running"),
    [jobs]
  );

  const completedJobs = useMemo(
    () => jobs.filter((job) => TERMINAL_STATUSES.has(job.status)),
    [jobs]
  );

  const requestCancel = useCallback(
    async (job: JobRecord) => {
      setActioning(`cancel:${job.job_id}`);
      setError(null);
      try {
        await cancelJob(job.job_id);
        await fetchJobsData();
      } catch {
        setError("Failed to cancel job.");
      } finally {
        setActioning(null);
      }
    },
    [fetchJobsData]
  );

  const removeJob = useCallback(
    async (job: JobRecord) => {
      setActioning(`delete:${job.job_id}`);
      setError(null);
      try {
        await deleteJob(job.job_id);
        await fetchJobsData();
      } catch {
        setError("Failed to remove job.");
      } finally {
        setActioning(null);
      }
    },
    [fetchJobsData]
  );

  const clearCompleted = useCallback(async () => {
    setActioning("clear-completed");
    setError(null);
    try {
      await clearCompletedJobs();
      await fetchJobsData();
    } catch {
      setError("Failed to clear completed jobs.");
    } finally {
      setActioning(null);
    }
  }, [fetchJobsData]);

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={3}>Activity</Title>
          <Text size="sm" c="dimmed">
            Running and queued jobs are shown at the top. Completed jobs are listed below.
          </Text>
        </div>
        <Group>
          <Button
            variant="default"
            onClick={() => void fetchJobsData("refresh")}
            loading={refreshing}
            disabled={loading || actioning !== null}
          >
            Refresh
          </Button>
          <Button
            color="red"
            onClick={() => void clearCompleted()}
            loading={actioning === "clear-completed"}
            disabled={loading || completedJobs.length === 0 || (actioning !== null && actioning !== "clear-completed")}
          >
            Clear Completed
          </Button>
        </Group>
      </Group>

      {error ? (
        <Text size="sm" c="red">
          {error}
        </Text>
      ) : null}

      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Current jobs</Text>
          <Group gap="xs">
            <Badge color="yellow">Queued: {summary?.queued ?? activeJobs.filter((job) => job.status === "queued").length}</Badge>
            <Badge color="blue">Running: {summary?.running ?? activeJobs.filter((job) => job.status === "running").length}</Badge>
          </Group>
        </Group>

        {loading ? (
          <Group>
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Loading jobs...
            </Text>
          </Group>
        ) : activeJobs.length === 0 ? (
          <Text size="sm" c="dimmed">
            No queued or running jobs.
          </Text>
        ) : (
          <ScrollArea type="auto">
            <Table striped highlightOnHover withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Type</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Queued</Table.Th>
                  <Table.Th>Runtime</Table.Th>
                  <Table.Th>Action</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {activeJobs.map((job) => (
                  <Table.Tr key={job.job_id}>
                    <Table.Td>{job.kind}</Table.Td>
                    <Table.Td>
                      <Badge color={statusColor(job.status)} variant="light">
                        {job.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{formatTime(job.queued_at)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{formatRuntime(job)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="compact-xs"
                        color="red"
                        variant="light"
                        onClick={() => void requestCancel(job)}
                        loading={actioning === `cancel:${job.job_id}`}
                        disabled={actioning !== null && actioning !== `cancel:${job.job_id}`}
                      >
                        Cancel
                      </Button>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Card>

      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Completed jobs</Text>
          <Group gap="xs">
            <Badge color="green">Succeeded: {summary?.succeeded ?? completedJobs.filter((job) => job.status === "succeeded").length}</Badge>
            <Badge color="red">Failed: {summary?.failed ?? completedJobs.filter((job) => job.status === "failed").length}</Badge>
            <Badge color="gray">Canceled: {summary?.canceled ?? completedJobs.filter((job) => job.status === "canceled").length}</Badge>
          </Group>
        </Group>

        {loading ? null : completedJobs.length === 0 ? (
          <Text size="sm" c="dimmed">
            No completed jobs yet.
          </Text>
        ) : (
          <ScrollArea h={460} type="auto">
            <Table striped highlightOnHover withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Type</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th>Queued</Table.Th>
                  <Table.Th>Finished</Table.Th>
                  <Table.Th>Runtime</Table.Th>
                  <Table.Th>Action</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {completedJobs.map((job) => (
                  <Table.Tr key={job.job_id}>
                    <Table.Td>{job.kind}</Table.Td>
                    <Table.Td>
                      <Badge color={statusColor(job.status)} variant="light">
                        {job.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{formatTime(job.queued_at)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{formatTime(job.finished_at)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="xs" c="dimmed">{formatRuntime(job)}</Text>
                    </Table.Td>
                    <Table.Td>
                      <Button
                        size="compact-xs"
                        color="red"
                        variant="subtle"
                        onClick={() => void removeJob(job)}
                        loading={actioning === `delete:${job.job_id}`}
                        disabled={actioning !== null && actioning !== `delete:${job.job_id}`}
                      >
                        Clear
                      </Button>
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
