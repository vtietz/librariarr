import { Stack, Title } from "@mantine/core";
import { useState } from "react";
import { runFullReconcile } from "../api/client";
import type { RuntimeStatusResponse } from "../api/client";
import DeletedFilesCard from "./dashboard/DeletedFilesCard";
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
  const [queuingReconcile, setQueuingReconcile] = useState(false);

  const taskIsRunning = runtimeStatus?.current_task?.state === "running";
  const runningReconcile = queuingReconcile || taskIsRunning;

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

      <DeletedFilesCard />
    </Stack>
  );
}
