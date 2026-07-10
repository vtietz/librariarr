import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Stack,
  Table,
  Text,
  Title
} from "@mantine/core";
import { useState } from "react";
import type { StatusResponse } from "../api/client";
import { triggerReconcile } from "../api/client";

const formatTime = (epochSeconds: number | null | undefined): string =>
  epochSeconds ? new Date(epochSeconds * 1000).toLocaleString() : "–";

export default function StatusPanel({
  status,
  onRefresh
}: {
  status: StatusResponse | null;
  onRefresh: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const run = async (scope: "full" | "consistency") => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await triggerReconcile(scope);
      setMessage(result.queued ? `${scope} reconcile queued` : `${scope} reconcile finished`);
      onRefresh();
    } catch (error) {
      setMessage(`Failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  };

  if (!status) {
    return <Text c="dimmed">Loading status…</Text>;
  }
  const report = status.last_report;

  return (
    <Stack gap="md">
      <Group>
        <Badge color={status.running ? "yellow" : "green"} size="lg">
          {status.running ? `running: ${status.running_scope}` : "idle"}
        </Badge>
        <Badge color={status.runtime_loop_active ? "green" : "gray"} size="lg">
          {status.runtime_loop_active ? "runtime loop active" : "runtime loop off"}
        </Badge>
        <Button size="xs" onClick={() => run("consistency")} loading={busy}>
          Run consistency pass
        </Button>
        <Button size="xs" variant="light" onClick={() => run("full")} loading={busy}>
          Run full pass
        </Button>
      </Group>
      {message && <Alert color="blue">{message}</Alert>}
      {status.last_error && <Alert color="red">Last error: {status.last_error}</Alert>}

      {report && (
        <Card withBorder>
          <Title order={5}>
            Last run: {report.scope} {report.dry_run ? "(dry-run)" : ""}
          </Title>
          <Group gap="xl" mt="xs">
            <Text size="sm">items: {report.items_seen}</Text>
            <Text size="sm">changed: {report.items_changed}</Text>
            <Text size="sm">unmatched: {report.unmatched.length}</Text>
            <Text size="sm">warnings: {report.warnings.length}</Text>
            <Text size="sm">errors: {report.errors.length}</Text>
            <Text size="sm">{report.duration_seconds.toFixed(2)}s</Text>
          </Group>
          {report.warnings.length > 0 && (
            <Alert color="yellow" mt="sm">
              {report.warnings.slice(0, 5).map((warning) => (
                <Text size="sm" key={warning}>
                  {warning}
                </Text>
              ))}
            </Alert>
          )}
          {report.actions.length > 0 && (
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
                <Table.Td>{run.scope}</Table.Td>
                <Table.Td>{run.items_seen ?? "–"}</Table.Td>
                <Table.Td>{run.items_changed ?? "–"}</Table.Td>
                <Table.Td>
                  {run.error ? (
                    <Badge color="red">error</Badge>
                  ) : (
                    <Badge color="green">ok</Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
