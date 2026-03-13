import { Badge, Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { useState } from "react";
import {
  runDryRun,
  runRadarrDiagnostics,
  runReconcileNow,
  runSonarrDiagnostics
} from "../api/client";
import MapperOverviewPanels from "./MapperOverviewPanels";
import type { ConfigModel, Issue } from "../types/config";

type Props = {
  draft: ConfigModel;
  onDryRunSummary: (summary: string) => void;
  onStatuses: (radarrStatus: string, sonarrStatus: string) => void;
};

export default function DiagnosticsPanel({ draft, onDryRunSummary, onStatuses }: Props) {
  const [radarrIssues, setRadarrIssues] = useState<Issue[]>([]);
  const [sonarrIssues, setSonarrIssues] = useState<Issue[]>([]);
  const [dryRunIssues, setDryRunIssues] = useState<Issue[]>([]);
  const [maintenanceMessage, setMaintenanceMessage] = useState<string | null>(null);

  const executeRadarr = async () => {
    const result = await runRadarrDiagnostics();
    setRadarrIssues(result.issues);
    onStatuses(result.status, "idle");
  };

  const executeSonarr = async () => {
    const result = await runSonarrDiagnostics();
    setSonarrIssues(result.issues);
    onStatuses("idle", result.status);
  };

  const executeDryRun = async () => {
    const result = await runDryRun();
    setDryRunIssues(result.issues);
    if (result.summary) {
      onDryRunSummary(
        `Movies=${result.summary.movie_folders_detected}, Series=${result.summary.series_folders_detected}, Mappings=${result.summary.root_mappings}`
      );
    }
  };

  const executeMaintenanceReconcile = async () => {
    try {
      const result = await runReconcileNow();
      const durationSuffix =
        typeof result.duration_ms === "number" ? ` (${result.duration_ms} ms)` : "";
      const pendingSuffix =
        result.ingest_pending === true ? " Ingest still has pending quiescent candidates." : "";
      setMaintenanceMessage(`${result.message}${durationSuffix}${pendingSuffix}`);
    } catch (error: unknown) {
      const message =
        typeof error === "object" &&
        error !== null &&
        "message" in error &&
        typeof (error as { message?: unknown }).message === "string"
          ? (error as { message: string }).message
          : "Failed to trigger reconcile.";
      setMaintenanceMessage(message);
    }
  };

  return (
    <Stack>
      <Title order={3}>Diagnostics, Dry-Run & Maintenance</Title>
      <Text size="sm" c="dimmed">
        Available now: run diagnostics, run dry-run, and trigger a full reconcile cycle.
      </Text>

      <MapperOverviewPanels draft={draft} />

      <Group>
        <Button onClick={executeRadarr}>Run Radarr Diagnostics</Button>
        <Button onClick={executeSonarr}>Run Sonarr Diagnostics</Button>
        <Button variant="light" onClick={executeDryRun}>
          Run Dry-Run
        </Button>
        <Button variant="filled" color="grape" onClick={executeMaintenanceReconcile}>
          Run Reconcile Now
        </Button>
      </Group>

      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>Maintenance</Text>
          <Badge>{maintenanceMessage ? 1 : 0}</Badge>
        </Group>
        <Text c="dimmed" size="sm">
          {maintenanceMessage ?? "No maintenance action executed yet."}
        </Text>
      </Card>

      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>Radarr Issues</Text>
          <Badge>{radarrIssues.length}</Badge>
        </Group>
        {radarrIssues.length === 0 ? (
          <Text c="dimmed" size="sm">
            No issues reported.
          </Text>
        ) : (
          <Stack gap="xs" mt="sm">
            {radarrIssues.map((issue, index) => (
              <Text key={`radarr-${index}`} size="sm">
                [{issue.severity}] {issue.message}
              </Text>
            ))}
          </Stack>
        )}
      </Card>

      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>Sonarr Issues</Text>
          <Badge>{sonarrIssues.length}</Badge>
        </Group>
        {sonarrIssues.length === 0 ? (
          <Text c="dimmed" size="sm">
            No issues reported.
          </Text>
        ) : (
          <Stack gap="xs" mt="sm">
            {sonarrIssues.map((issue, index) => (
              <Text key={`sonarr-${index}`} size="sm">
                [{issue.severity}] {issue.message}
              </Text>
            ))}
          </Stack>
        )}
      </Card>

      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>Dry-Run Issues</Text>
          <Badge>{dryRunIssues.length}</Badge>
        </Group>
        {dryRunIssues.length === 0 ? (
          <Text c="dimmed" size="sm">
            No issues reported.
          </Text>
        ) : (
          <Stack gap="xs" mt="sm">
            {dryRunIssues.map((issue, index) => (
              <Text key={`dry-${index}`} size="sm">
                [{issue.severity}] {issue.message}
              </Text>
            ))}
          </Stack>
        )}
      </Card>
    </Stack>
  );
}
