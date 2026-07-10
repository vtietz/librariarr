import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip
} from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import type { ReconcileReport, StatusResponse } from "../api/client";
import { triggerReconcile } from "../api/client";

const formatTime = (epochSeconds: number | null | undefined): string =>
  epochSeconds ? new Date(epochSeconds * 1000).toLocaleString() : "–";

type PendingRun = { scope: string; since: number };

function StatTile({
  label,
  value,
  hint,
  attention
}: {
  label: string;
  value: string;
  hint?: string;
  attention?: boolean;
}) {
  return (
    <Card withBorder padding="sm">
      <Text size="xl" fw={700}>
        {value}
      </Text>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      {attention && (
        <Badge color="yellow" size="xs" mt={4}>
          needs attention
        </Badge>
      )}
      {hint && !attention && (
        <Text size="xs" c="dimmed" mt={4}>
          {hint}
        </Text>
      )}
    </Card>
  );
}

function LibraryGauges({
  report,
  asOf
}: {
  report: ReconcileReport;
  asOf: number | null;
}) {
  const stats = report.stats ?? {};
  const moviesTotal = stats.movies_total ?? 0;
  const seriesTotal = stats.series_total ?? 0;
  const episodesTotal = stats.episodes_total ?? 0;
  const unmatched = report.unmatched.length;
  const tiles: { label: string; value: string; hint?: string; attention?: boolean }[] = [];

  if (moviesTotal > 0) {
    tiles.push({
      label: "movies in sync",
      value: `${stats.movies_in_sync ?? 0} / ${moviesTotal}`,
      hint: stats.movies_without_file ? `${stats.movies_without_file} without file` : undefined
    });
  }
  if (seriesTotal > 0) {
    tiles.push({
      label: "episodes in sync",
      value: `${stats.episodes_in_sync ?? 0} / ${episodesTotal}`,
      hint: `${seriesTotal} series`
    });
  }
  if (stats.managed_video_files !== undefined) {
    tiles.push({ label: "video files in managed tree", value: String(stats.managed_video_files) });
  }
  tiles.push({
    label: "unmatched folders",
    value: String(unmatched),
    attention: unmatched > 0
  });
  tiles.push({
    label: "warnings (last full pass)",
    value: String(report.warnings.length),
    attention: report.warnings.length > 0
  });

  return (
    <Card withBorder>
      <Group justify="space-between">
        <Title order={5}>Library state</Title>
        <Text size="xs" c="dimmed">
          as of last full pass: {formatTime(asOf)}
        </Text>
      </Group>
      <SimpleGrid cols={{ base: 2, sm: 3, md: 5 }} mt="sm">
        {tiles.map((tile) => (
          <StatTile key={tile.label} {...tile} />
        ))}
      </SimpleGrid>
    </Card>
  );
}

function ReportCard({ title, report }: { title: string; report: ReconcileReport }) {
  const fullScope = report.scope === "full";

  return (
    <Card withBorder>
      <Title order={5}>{title}</Title>
      <Group gap="xl" mt="xs">
        <Text size="sm">Arr items checked: {report.items_seen}</Text>
        <Text size="sm">Items changed: {report.items_changed}</Text>
        <Text size="sm">Unmatched folders: {report.unmatched.length}</Text>
        <Text size="sm">warnings: {report.warnings.length}</Text>
        <Text size="sm">errors: {report.errors.length}</Text>
        <Text size="sm">{report.duration_seconds.toFixed(2)}s</Text>
      </Group>
      <Alert color="blue" mt="sm">
        <Text size="sm">
          "Unmatched" means managed folders that could not be linked or confidently auto-added in
          Arr.
        </Text>
        <Text size="sm">
          "Arr items checked" counts Arr movies/series scanned in this run, not total files in your
          managed root.
        </Text>
      </Alert>
      {!fullScope && (
        <Alert color="gray" mt="sm">
          Full discovery of unmatched folders happens during a full pass. Consistency passes focus on
          already known Arr items.
        </Alert>
      )}
      {report.errors.length > 0 && (
        <Alert color="red" mt="sm">
          {report.errors.slice(0, 5).map((error) => (
            <Text size="sm" key={error}>
              {error}
            </Text>
          ))}
        </Alert>
      )}
      {report.warnings.length > 0 && (
        <Alert color="yellow" mt="sm">
          {report.warnings.slice(0, 5).map((warning) => (
            <Text size="sm" key={warning}>
              {warning}
            </Text>
          ))}
        </Alert>
      )}
      {report.actions.length === 0 ? (
        <Text size="sm" c="dimmed" mt="sm">
          No filesystem or Arr changes{report.dry_run ? " would be made" : " were needed"} —
          everything is in sync.
        </Text>
      ) : (
        <Table mt="sm" striped withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Action</Table.Th>
              <Table.Th>Detail</Table.Th>
              <Table.Th>Target</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {report.actions.slice(0, 50).map((action, index) => (
              <Table.Tr key={index}>
                <Table.Td>
                  <Badge variant="light">{action.kind}</Badge>
                </Table.Td>
                <Table.Td>{action.detail}</Table.Td>
                <Table.Td style={{ wordBreak: "break-all" }}>
                  {action.target ?? action.source ?? ""}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Card>
  );
}

export default function StatusPanel({
  status,
  onRefresh
}: {
  status: StatusResponse | null;
  onRefresh: () => void;
}) {
  const [pending, setPending] = useState<PendingRun | null>(null);
  const [finishedNote, setFinishedNote] = useState<string | null>(null);
  const [preview, setPreview] = useState<ReconcileReport | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pendingRef = useRef<PendingRun | null>(null);
  pendingRef.current = pending;

  const running = status?.running ?? false;

  // Poll faster while a run is queued or in flight so the lifecycle is visible.
  useEffect(() => {
    if (!pending && !running) return;
    const timer = setInterval(onRefresh, 2000);
    return () => clearInterval(timer);
  }, [pending, running, onRefresh]);

  // Detect completion of the run we queued.
  useEffect(() => {
    const current = pendingRef.current;
    if (!current || !status?.last_finished_at) return;
    if (status.last_finished_at >= current.since && !status.running) {
      setPending(null);
      setFinishedNote(
        status.last_error
          ? `${current.scope} pass finished with an error: ${status.last_error}`
          : `${current.scope} pass finished — results below.`
      );
    }
  }, [status]);

  const queueRun = async (scope: "full" | "consistency") => {
    setError(null);
    setFinishedNote(null);
    setPreview(null);
    try {
      const result = await triggerReconcile(scope);
      if (result.queued) {
        setPending({ scope, since: Date.now() / 1000 });
      } else if (result.report) {
        setFinishedNote(`${scope} pass finished — results below.`);
      }
      onRefresh();
    } catch (requestError) {
      setError(`Could not start reconcile: ${String(requestError)}`);
    }
  };

  const runPreview = async () => {
    setError(null);
    setFinishedNote(null);
    setPreviewLoading(true);
    try {
      const result = await triggerReconcile("full", true);
      setPreview(result.report ?? null);
    } catch (requestError) {
      setError(`Preview failed: ${String(requestError)}`);
    } finally {
      setPreviewLoading(false);
    }
  };

  if (!status) {
    return <Text c="dimmed">Loading status…</Text>;
  }

  const busy = running || pending !== null;

  return (
    <Stack gap="md">
      <Group>
        <Badge color={running ? "yellow" : "green"} size="lg">
          {running ? `running: ${status.running_scope}` : "idle"}
        </Badge>
        <Badge color={status.runtime_loop_active ? "green" : "gray"} size="lg">
          {status.runtime_loop_active ? "runtime loop active" : "runtime loop off"}
        </Badge>
        <Tooltip label="Verify every Arr item against the managed tree (no folder scan). Runs in the background; takes seconds.">
          <Button size="xs" onClick={() => queueRun("consistency")} disabled={busy}>
            Run consistency pass
          </Button>
        </Tooltip>
        <Tooltip label="Consistency + folder scan, discovery/auto-add, and cleanup of stale projections. Runs in the background.">
          <Button size="xs" variant="light" onClick={() => queueRun("full")} disabled={busy}>
            Run full pass
          </Button>
        </Tooltip>
        <Tooltip label="Compute the full plan without changing anything, and show it here.">
          <Button
            size="xs"
            variant="outline"
            onClick={runPreview}
            loading={previewLoading}
            disabled={running}
          >
            Preview (dry-run)
          </Button>
        </Tooltip>
      </Group>

      {pending && !running && (
        <Alert color="blue" icon={<Loader size="xs" />}>
          {pending.scope} pass queued — it starts after the debounce window (a few seconds)
          and will show as “running” above.
        </Alert>
      )}
      {running && (
        <Alert color="yellow" icon={<Loader size="xs" />}>
          <Stack gap={6}>
            <Text size="sm">
              {status.running_scope} pass is running
              {status.progress
                ? `: ${status.progress.phase}` +
                  (status.progress.total > 0
                    ? ` — ${status.progress.current} / ${status.progress.total}`
                    : "…")
                : "…"}
            </Text>
            <Progress
              value={
                status.progress && status.progress.total > 0
                  ? (status.progress.current / status.progress.total) * 100
                  : 100
              }
              animated={!status.progress || status.progress.total === 0}
              size="sm"
            />
          </Stack>
        </Alert>
      )}
      {finishedNote && !busy && <Alert color="green">{finishedNote}</Alert>}
      {error && <Alert color="red">{error}</Alert>}
      {status.last_error && !finishedNote && (
        <Alert color="red">Last error: {status.last_error}</Alert>
      )}

      {status.last_full_report && (
        <LibraryGauges report={status.last_full_report} asOf={status.last_full_finished_at} />
      )}
      {!status.last_full_report && !running && (
        <Alert color="gray">
          No full pass has run yet — library state gauges appear after the first one.
        </Alert>
      )}

      {preview && <ReportCard title="Preview: what a full pass would do (dry-run)" report={preview} />}

      {status.last_report && (
        <ReportCard
          title={`Last run: ${status.last_report.scope}${status.last_report.dry_run ? " (dry-run)" : ""}`}
          report={status.last_report}
        />
      )}

      <Card withBorder>
        <Title order={5}>Recent runs</Title>
        <Table mt="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Finished</Table.Th>
              <Table.Th>Scope</Table.Th>
              <Table.Th>Arr items checked</Table.Th>
              <Table.Th>Changed</Table.Th>
              <Table.Th>Unmatched folders</Table.Th>
              <Table.Th>Result</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {status.history.map((run, index) => (
              <Table.Tr key={index}>
                <Table.Td>{formatTime(run.finished_at)}</Table.Td>
                <Table.Td>
                  {run.scope}
                  {run.dry_run ? " (dry-run)" : ""}
                </Table.Td>
                <Table.Td>{run.items_seen ?? "–"}</Table.Td>
                <Table.Td>{run.items_changed ?? "–"}</Table.Td>
                <Table.Td>{run.unmatched ?? "–"}</Table.Td>
                <Table.Td>
                  {run.error ? <Badge color="red">error</Badge> : <Badge color="green">ok</Badge>}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
