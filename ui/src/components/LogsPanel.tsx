import { Badge, Button, Card, Group, Loader, ScrollArea, Stack, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getDockerLogStreamUrl, getDockerLogs, type DockerLogItem } from "../api/client";

const LEVEL_COLOR: Record<string, string> = {
  TRACE: "gray",
  DEBUG: "blue",
  INFO: "teal",
  WARNING: "yellow",
  ERROR: "red",
  CRITICAL: "grape",
  UNKNOWN: "gray"
};

function levelColor(level: string): string {
  const normalized = level.toUpperCase();
  return LEVEL_COLOR[normalized] ?? "gray";
}

export default function LogsPanel() {
  const container = "librariarr";
  const [logs, setLogs] = useState<DockerLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "live" | "disconnected">(
    "connecting"
  );

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await getDockerLogs({ container, tail: 250 });
      setLogs(result.items);
    } catch (fetchError: unknown) {
      const detail =
        typeof fetchError === "object" &&
        fetchError !== null &&
        "response" in fetchError &&
        typeof (fetchError as { response?: { data?: { detail?: unknown } } }).response?.data
          ?.detail === "string"
          ? ((fetchError as { response: { data: { detail: string } } }).response.data.detail ??
              null)
          : null;
      setError(detail || "Failed to load Docker logs.");
    } finally {
      setLoading(false);
    }
  }, [container]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  useEffect(() => {
    const source = new EventSource(getDockerLogStreamUrl({ container, tail: 0 }));
    setStreamState("connecting");

    source.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as DockerLogItem;
        setLogs((current) => [parsed, ...current].slice(0, 1000));
        setStreamState("live");
        setError(null);
      } catch {
        setStreamState("disconnected");
      }
    };

    source.onerror = () => {
      setStreamState("disconnected");
    };

    return () => {
      source.close();
    };
  }, [container]);

  const countLabel = useMemo(() => logs.length.toString(), [logs.length]);
  const streamColor =
    streamState === "live" ? "teal" : streamState === "connecting" ? "blue" : "gray";

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Title order={3}>Docker Logs</Title>
          <Text size="sm" c="dimmed">
            Latest entries are shown first.
          </Text>
        </div>
        <Group>
          <Badge variant="light">Container: {container}</Badge>
          <Badge color={streamColor} variant="light">
            {streamState === "live"
              ? "Live"
              : streamState === "connecting"
                ? "Connecting"
                : "Disconnected"}
          </Badge>
          <Button onClick={() => void fetchLogs()} disabled={loading}>
            Refresh
          </Button>
        </Group>
      </Group>

      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Entries</Text>
          <Badge>{countLabel}</Badge>
        </Group>

        {loading ? (
          <Group>
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Loading logs...
            </Text>
          </Group>
        ) : error ? (
          <Text size="sm" c="red">
            {error}
          </Text>
        ) : logs.length === 0 ? (
          <Text size="sm" c="dimmed">
            No log lines returned.
          </Text>
        ) : (
          <ScrollArea h={520} type="auto">
            <Stack gap="xs">
              {logs.map((entry, index) => (
                <Text key={`${index}-${entry.line}`} size="sm" c={levelColor(entry.level)}>
                  [{entry.level}] {entry.line}
                </Text>
              ))}
            </Stack>
          </ScrollArea>
        )}
      </Card>
    </Stack>
  );
}
