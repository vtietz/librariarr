import { Card, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import { getDiscoveryWarnings, runFullReconcile } from "../api/client";
import type { JobsSummary, RuntimeStatusResponse } from "../api/client";
import { formatAge, formatTaskDuration, formatTaskQueuedAt } from "./dashboardFormatters";
import ActiveReconcilePanel from "./dashboard/ActiveReconcilePanel";
import DiscoveryWarningsCard from "./dashboard/DiscoveryWarningsCard";
import PerRootInsightsCard from "./dashboard/PerRootInsightsCard";
import SystemStatusCards from "./dashboard/SystemStatusCards";
import TaskSlotsCard, {
  type DashboardTaskStatus,
  type TaskSlot,
} from "./dashboard/TaskSlotsCard";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
  jobsSummary: JobsSummary | null;
};

export default function Dashboard({
  hasUnsavedChanges,
  runtimeStatus,
  jobsSummary,
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

  const handleRunReconcile = async () => {
    setRunningReconcile(true);
    try {
      await runFullReconcile();
    } catch (error) {
      console.error("[Dashboard] Failed to queue maintenance reconcile", error);
    } finally {
      setRunningReconcile(false);
    }
  };

  const queuedChanges = runtimeStatus?.dirty_paths_queued ?? 0;
  const knownLinksInMemory =
    runtimeStatus?.known_links_in_memory ??
    runtimeStatus?.mapped_cache?.entries_total ??
    0;
  const mappedEntriesTotal =
    runtimeStatus?.mapped_cache?.entries_total ?? knownLinksInMemory;

  const taskSlots = useMemo<{ slots: TaskSlot[]; uncategorizedCount: number }>(() => {
        const toTaskStatus = (status: string): DashboardTaskStatus => {
          if (status === "queued" || status === "running" || status === "error") {
            return status;
          }
          return "idle";
        };

    const pendingTasks = runtimeStatus?.pending_tasks ?? [];
    const consumedTaskIds = new Set<string>();

    const findPendingTask = (
      predicate: (task: (typeof pendingTasks)[number]) => boolean
    ) => {
      const task = pendingTasks.find(predicate);
      if (task) {
        consumedTaskIds.add(task.id);
      }
      return task;
    };

    const filesystemTask = findPendingTask((task) => task.id === "filesystem-debounce");
    const manualReconcileTask = findPendingTask((task) =>
      task.name.toLowerCase().includes("full reconcile")
    );
    const mappedRefreshTask = findPendingTask((task) =>
      task.name.toLowerCase().includes("refresh mapped")
    );
    const discoverySnapshotTask = findPendingTask((task) =>
      task.name.toLowerCase().includes("discovery snapshot rebuild")
    );
    const reconcileCycleTask = findPendingTask((task) =>
      task.name.toLowerCase().includes("reconcile cycle")
    );

    const slots: TaskSlot[] = [];

    slots.push({
      id: "filesystem-debounce",
      name: "Filesystem Debounce",
      source: "filesystem",
      status: filesystemTask?.status ?? "idle",
      detail:
        filesystemTask?.detail ??
        `${queuedChanges} filesystem changes waiting for runtime reconcile`,
      queuedAt: filesystemTask ? formatTaskQueuedAt(filesystemTask) : "-",
      duration: filesystemTask ? formatTaskDuration(filesystemTask) : "-",
    });

    slots.push({
      id: "manual-reconcile",
      name: "Full Reconcile Job",
      source: "job-manager",
      status: manualReconcileTask?.status ?? "idle",
      detail: manualReconcileTask?.detail ?? "On-demand full reconcile (all media)",
      queuedAt: manualReconcileTask ? formatTaskQueuedAt(manualReconcileTask) : "-",
      duration: manualReconcileTask ? formatTaskDuration(manualReconcileTask) : "-",
    });

    const mappedStatus =
      runtimeStatus?.mapped_cache?.building
        ? "running"
        : mappedRefreshTask?.status ?? "idle";
    if (mappedStatus !== "idle") {
      slots.push({
        id: "mapped-cache-refresh",
        name: "Mapped Cache Refresh",
        source: "cache",
        status: mappedStatus,
        detail: runtimeStatus?.mapped_cache?.building
          ? "Rebuilding mapped directory index"
          : mappedRefreshTask?.detail ?? "Ready",
        queuedAt: mappedRefreshTask ? formatTaskQueuedAt(mappedRefreshTask) : "-",
        duration:
          typeof runtimeStatus?.mapped_cache?.last_build_duration_ms === "number"
            ? `${runtimeStatus.mapped_cache.last_build_duration_ms} ms`
            : mappedRefreshTask
              ? formatTaskDuration(mappedRefreshTask)
              : "-",
      });
    }

    const discoveryStatus =
      discoverySnapshotTask?.status ??
      (runtimeStatus?.discovery_cache?.building ? "running" : "idle");
    if (discoveryStatus !== "idle") {
      slots.push({
        id: "discovery-snapshot-rebuild",
        name: "Discovery Snapshot Rebuild",
        source: "cache",
        status: discoveryStatus,
        detail:
          discoverySnapshotTask?.detail ??
          (runtimeStatus?.discovery_cache?.building
            ? "Rebuilding discovery warnings snapshot"
            : "Ready"),
        queuedAt: discoverySnapshotTask
          ? formatTaskQueuedAt(discoverySnapshotTask)
          : "-",
        duration: discoverySnapshotTask
          ? formatTaskDuration(discoverySnapshotTask)
          : typeof runtimeStatus?.discovery_cache?.last_build_duration_ms === "number"
            ? `${runtimeStatus.discovery_cache.last_build_duration_ms} ms`
            : "-",
      });
    }

    if (reconcileCycleTask && reconcileCycleTask.status !== "idle") {
      slots.push({
        id: "reconcile-cycle",
        name: "Reconcile Cycle",
        source: "runtime",
        status: reconcileCycleTask.status,
        detail: reconcileCycleTask.detail || reconcileCycleTask.status,
        queuedAt: formatTaskQueuedAt(reconcileCycleTask),
        duration: formatTaskDuration(reconcileCycleTask),
      });
    }

    const uncategorized: TaskSlot[] = pendingTasks
      .filter((task) => !consumedTaskIds.has(task.id))
      .map((task) => ({
        id: `uncategorized-${task.id}`,
        name: task.name || "Background Task",
        source: task.source || "task-manager",
        status: toTaskStatus(task.status),
        detail: task.detail || task.status,
        queuedAt: formatTaskQueuedAt(task),
        duration: formatTaskDuration(task),
      }));

    const merged = [...slots, ...uncategorized];
    const withSignal = merged.filter((slot) => slot.status !== "idle");

    const fallbackSlots: TaskSlot[] = [
      ...slots,
      {
        id: "reconcile-cycle",
        name: "Reconcile Cycle",
        source: "runtime",
        status: "idle",
        detail: "Waiting for next reconcile cycle",
        queuedAt: formatAge(runtimeStatus?.last_reconcile?.finished_at),
        duration:
          typeof runtimeStatus?.last_reconcile?.duration_seconds === "number"
            ? `${runtimeStatus.last_reconcile.duration_seconds.toFixed(1)}s`
            : "-",
      },
    ];

    return {
      slots: withSignal.length > 0 ? merged : fallbackSlots,
      uncategorizedCount: uncategorized.length,
    };
  }, [runtimeStatus, queuedChanges]);

  return (
    <Stack gap="md">
      <Title order={3}>Dashboard</Title>
      <Text size="sm" c="dimmed">
        Primary progress is shown in Active Reconcile. Task Details below show supporting background work.
      </Text>

      <SystemStatusCards
        hasUnsavedChanges={hasUnsavedChanges}
        runtimeStatus={runtimeStatus}
        jobsSummary={jobsSummary}
      />

      <ActiveReconcilePanel
        runtimeStatus={runtimeStatus}
        runningReconcile={runningReconcile}
        onRunFullReconcile={handleRunReconcile}
      />

      <Text fw={600} size="sm" c="dimmed">Workload & Caches</Text>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Card withBorder h={128}>
          <Text fw={600}>Filesystem Queue</Text>
          <Text size="sm" c="dimmed">
            {queuedChanges} pending fs changes
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            Next debounce run in {runtimeStatus?.next_event_reconcile_in_seconds ?? 0}s
          </Text>
        </Card>
        <Card withBorder h={128}>
          <Text fw={600}>Mapped Index Entries</Text>
          <Text size="sm" c="dimmed">
            {mappedEntriesTotal} mapped directories in cache
          </Text>
          <Text size="sm" c="dimmed" mt="xs">
            mapped cache {runtimeStatus?.mapped_cache?.building ? "rebuilding" : "ready"}
          </Text>
        </Card>
      </SimpleGrid>

      <DiscoveryWarningsCard discoveryWarnings={discoveryWarnings} />

      <PerRootInsightsCard />

      <TaskSlotsCard
        taskSlots={taskSlots.slots}
        uncategorizedTaskCount={taskSlots.uncategorizedCount}
      />
    </Stack>
  );
}
