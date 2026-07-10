import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
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

function ReportCard({ title, report }: { title: string; report: ReconcileReport }) {
  return (
    <Card withBorder>
      <Title order={5}>{title}</Title>
      <Group gap="xl" mt="xs">
        <Text size="sm">items: {report.items_seen}</Text>
        <Text size="sm">changed: {report.items_changed}</Text>
        <Text size="sm">unmatched: {report.unmatched.length}</Text>
        <Text size="sm">warnings: {report.warnings.length}</Text>
        <Text size="sm">errors: {report.errors.length}</Text>
        <Text size="sm">{report.duration_seconds.toFixed(2)}s</Text>
      </Group>
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
          {status.running_scope} pass is running… results appear below when it finishes.
        </Alert>
      )}
      {finishedNote && !busy && <Alert color="green">{finishedNote}</Alert>}
      {error && <Alert color="red">{error}</Alert>}
      {status.last_error && !finishedNote && (
        <Alert color="red">Last error: {status.last_error}</Alert>
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
              <Table.Th>Items</Table.Th>
              <Table.Th>Changed</Table.Th>
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
