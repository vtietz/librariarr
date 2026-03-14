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
  const [loadingRadarr, setLoadingRadarr] = useState(false);
  const [loadingSonarr, setLoadingSonarr] = useState(false);
  const [loadingDryRun, setLoadingDryRun] = useState(false);
  const [loadingReconcile, setLoadingReconcile] = useState(false);

  const executeRadarr = async () => {
    setLoadingRadarr(true);
    try {
      const result = await runRadarrDiagnostics();
      setRadarrIssues(result.issues);
      onStatuses(result.status, "idle");
    } catch (error: unknown) {
      console.error("[Diagnostics] Radarr diagnostics failed:", error);
      setRadarrIssues([{ severity: "error", message: "Request failed. Check browser console and docker logs." }]);
    } finally {
      setLoadingRadarr(false);
    }
  };

  const executeSonarr = async () => {
    setLoadingSonarr(true);
    try {
      const result = await runSonarrDiagnostics();
      setSonarrIssues(result.issues);
      onStatuses("idle", result.status);
    } catch (error: unknown) {
      console.error("[Diagnostics] Sonarr diagnostics failed:", error);
      setSonarrIssues([{ severity: "error", message: "Request failed. Check browser console and docker logs." }]);
    } finally {
      setLoadingSonarr(false);
    }
  };

  const executeDryRun = async () => {
    setLoadingDryRun(true);
    try {
      const result = await runDryRun();
      setDryRunIssues(result.issues);
      if (result.summary) {
        onDryRunSummary(
          `Movies=${result.summary.movie_folders_detected}, Series=${result.summary.series_folders_detected}, Mappings=${result.summary.root_mappings}`
        );
      }
    } catch (error: unknown) {
      console.error("[Diagnostics] Dry-run failed:", error);
      setDryRunIssues([{ severity: "error", message: "Request failed. Check browser console and docker logs." }]);
    } finally {
      setLoadingDryRun(false);
    }
  };

  const executeMaintenanceReconcile = async () => {
    setLoadingReconcile(true);
    try {
      const result = await runReconcileNow();
      const durationSuffix =
        typeof result.duration_ms === "number" ? ` (${result.duration_ms} ms)` : "";
      const pendingSuffix =
        result.ingest_pending === true ? " Ingest still has pending quiescent candidates." : "";
      setMaintenanceMessage(`${result.message}${durationSuffix}${pendingSuffix}`);
    } catch (error: unknown) {
      console.error("[Diagnostics] Reconcile failed:", error);
      const message =
        typeof error === "object" &&
        error !== null &&
        "message" in error &&
        typeof (error as { message?: unknown }).message === "string"
          ? (error as { message: string }).message
          : "Failed to trigger reconcile.";
      setMaintenanceMessage(message);
    } finally {
      setLoadingReconcile(false);
    }
  };

  return (
    <Stack>
      <Title order={3}>Troubleshooting (Advanced Users) & Maintenance</Title>
      <Text size="sm" c="dimmed">
        Use these actions when validating integrations, investigating errors, or forcing maintenance operations.
      </Text>

      <MapperOverviewPanels draft={draft} />

      <Group>
        <Button loading={loadingRadarr} onClick={() => void executeRadarr()}>Run Radarr Health Check</Button>
        <Button loading={loadingSonarr} onClick={() => void executeSonarr()}>Run Sonarr Health Check</Button>
        <Button variant="light" loading={loadingDryRun} onClick={() => void executeDryRun()}>
          Run Dry-Run Analysis
        </Button>
        <Button variant="filled" color="grape" loading={loadingReconcile} onClick={() => void executeMaintenanceReconcile()}>
          Run Full Reconcile Now
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
