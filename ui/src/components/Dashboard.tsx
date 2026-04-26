import { Stack, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import { getDiscoveryWarnings, runFullReconcile } from "../api/client";
import type { JobsSummary, RuntimeStatusResponse } from "../api/client";
import ActiveReconcilePanel from "./dashboard/ActiveReconcilePanel";
import DiscoveryWarningsCard from "./dashboard/DiscoveryWarningsCard";
import PerRootInsightsCard from "./dashboard/PerRootInsightsCard";
import SystemStatusCards from "./dashboard/SystemStatusCards";

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

  return (
    <Stack gap="md">
      <Title order={3}>Dashboard</Title>

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

      <PerRootInsightsCard />

      <DiscoveryWarningsCard discoveryWarnings={discoveryWarnings} />
    </Stack>
  );
}
