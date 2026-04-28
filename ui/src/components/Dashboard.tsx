import { Stack, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { getDiscoveryWarnings, runFullReconcile } from "../api/client";
import type { RuntimeStatusResponse } from "../api/client";
import DiscoveryWarningsCard from "./dashboard/DiscoveryWarningsCard";
import LibraryStatsCards from "./dashboard/LibraryStatsCards";
import PerRootInsightsCard from "./dashboard/PerRootInsightsCard";
import SyncStatusCard from "./dashboard/SyncStatusCard";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
};

export default function Dashboard({
  hasUnsavedChanges,
  runtimeStatus,
}: Props) {
  const [discoveryWarnings, setDiscoveryWarnings] = useState<Awaited<
    ReturnType<typeof getDiscoveryWarnings>
  > | null>(null);
  const [queuingReconcile, setQueuingReconcile] = useState(false);

  const taskIsRunning = runtimeStatus?.current_task?.state === "running";
  const runningReconcile = queuingReconcile || taskIsRunning;

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
    setQueuingReconcile(true);
    try {
      await runFullReconcile();
    } catch (error) {
      console.error("[Dashboard] Failed to queue maintenance reconcile", error);
    } finally {
      setQueuingReconcile(false);
    }
  };

  return (
    <Stack gap="md">
      <Title order={3}>Dashboard</Title>

      <LibraryStatsCards runtimeStatus={runtimeStatus} />

      <SyncStatusCard
        hasUnsavedChanges={hasUnsavedChanges}
        runtimeStatus={runtimeStatus}
        runningReconcile={runningReconcile}
        onRunFullReconcile={handleRunReconcile}
      />

      <PerRootInsightsCard runtimeStatus={runtimeStatus} />

      <DiscoveryWarningsCard discoveryWarnings={discoveryWarnings} />
    </Stack>
  );
}
