import { Badge, Button, Card, Group, Loader, ScrollArea, Stack, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getAppLogStreamUrl, getAppLogs, type LogItem } from "../api/client";

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

function mergeLatestLogs(current: LogItem[], incoming: LogItem[], limit = 1000): LogItem[] {
  const merged = [...incoming, ...current];
  const seen = new Set<string>();
  const result: LogItem[] = [];
  for (const entry of merged) {
    if (seen.has(entry.seq)) {
      continue;
    }
    seen.add(entry.seq);
    result.push(entry);
    if (result.length >= limit) {
      break;
    }
  }
  return result;
}

export default function LogsPanel() {
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [streamState, setStreamState] = useState<"connecting" | "live" | "disconnected">(
    "connecting"
  );

  const fetchLogs = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError(null);
    try {
      const result = await getAppLogs({ tail: 250 });
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
      const timedOut =
        typeof fetchError === "object" &&
        fetchError !== null &&
        "code" in fetchError &&
        (fetchError as { code?: string }).code === "ECONNABORTED";
      setError(
        detail ||
          (timedOut
            ? "Log snapshot request timed out. Live stream may still connect; use Refresh to retry."
            : "Failed to load logs.")
      );
    } finally {
      if (mode === "initial") {
        setLoading(false);
      } else {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchLogs("initial");
  }, [fetchLogs]);

  useEffect(() => {
    const source = new EventSource(getAppLogStreamUrl());
    setStreamState("connecting");

    source.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as LogItem & { connected?: boolean };
        if (parsed.connected) {
          setStreamState("live");
          setError(null);
          return;
        }
        setLogs((current) => mergeLatestLogs(current, [parsed]));
        setStreamState("live");
        setError(null);
      } catch {
        /* malformed SSE event — keep current list */
      }
    };

    source.onerror = () => {
      setStreamState("disconnected");
    };

    return () => {
      source.close();
    };
  }, []);

  const countLabel = useMemo(() => logs.length.toString(), [logs.length]);
  const streamColor =
    streamState === "live" ? "teal" : streamState === "connecting" ? "blue" : "gray";

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Title order={3}>Application Logs</Title>
          <Text size="sm" c="dimmed">
            Latest entries are shown first.
          </Text>
        </div>
        <Group>
          <Badge color={streamColor} variant="light">
            {streamState === "live"
              ? "Live"
              : streamState === "connecting"
                ? "Connecting"
                : "Disconnected"}
          </Badge>
          <Button onClick={() => void fetchLogs("refresh")} disabled={loading || refreshing} loading={refreshing}>
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
            No log entries yet.
          </Text>
        ) : (
          <ScrollArea h={520} type="auto">
            <Stack gap="xs">
              {logs.map((entry) => (
                <Text key={entry.seq} size="sm" c={levelColor(entry.level)}>
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
