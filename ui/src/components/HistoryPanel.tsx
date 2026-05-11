import { Badge, Button, Card, Group, Loader, ScrollArea, Stack, Text, Title } from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  clearHistory,
  deleteHistoryEvent,
  getHistory,
  type HistoryEvent,
  type HistoryResponse,
} from "../api/client";

const SCENARIO_LABELS: Record<string, string> = {
  "1": "Scenario 1: New import",
  "2": "Scenario 2: File replacement",
  "3": "Scenario 3: Managed rename/move",
  "4": "Scenario 4: Auto-add unmatched",
  "8": "Scenario 8: Cleanup/idempotency",
};

function scenarioLabel(scenario: string): string {
  return SCENARIO_LABELS[scenario] ?? `Scenario ${scenario}`;
}

function categoryColor(category: string): string {
  switch (category) {
    case "ingest":
      return "blue";
    case "replacement":
      return "orange";
    case "projection":
      return "teal";
    case "cleanup":
      return "gray";
    case "auto_add":
      return "green";
    case "deleted_files":
      return "red";
    default:
      return "dark";
  }
}

function formatTime(timestamp: number): string {
  return new Date(timestamp * 1000).toLocaleString();
}

export default function HistoryPanel() {
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [actioning, setActioning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(async (mode: "initial" | "refresh" = "refresh") => {
    if (mode === "initial") {
      setLoading(true);
    } else {
      setRefreshing(true);
    }
    setError(null);
    try {
      const data = await getHistory({ limit: 500 });
      setHistory(data);
    } catch {
      setError("Failed to load history.");
    } finally {
      if (mode === "initial") {
        setLoading(false);
      } else {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    void fetchHistory("initial");
  }, [fetchHistory]);

  const clearAll = useCallback(async () => {
    setActioning(true);
    setError(null);
    try {
      await clearHistory();
      await fetchHistory();
    } catch {
      setError("Failed to clear history.");
    } finally {
      setActioning(false);
    }
  }, [fetchHistory]);

  const removeOne = useCallback(
    async (event: HistoryEvent) => {
      setActioning(true);
      setError(null);
      try {
        await deleteHistoryEvent(event.id);
        await fetchHistory();
      } catch {
        setError("Failed to remove history entry.");
      } finally {
        setActioning(false);
      }
    },
    [fetchHistory]
  );

  const items = useMemo(() => history?.items ?? [], [history]);

  return (
    <Stack>
      <Group justify="space-between">
        <div>
          <Title order={3}>History</Title>
          <Text size="sm" c="dimmed">
            User-friendly event timeline aligned to reconcile scenarios.
          </Text>
        </div>
        <Group>
          <Button
            variant="default"
            onClick={() => void fetchHistory("refresh")}
            loading={refreshing}
            disabled={loading || actioning}
          >
            Refresh
          </Button>
          <Button color="red" onClick={() => void clearAll()} loading={actioning} disabled={loading}>
            Clear
          </Button>
        </Group>
      </Group>

      <Card withBorder>
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Events</Text>
          <Badge>{items.length}</Badge>
        </Group>

        {loading ? (
          <Group>
            <Loader size="sm" />
            <Text size="sm" c="dimmed">
              Loading history...
            </Text>
          </Group>
        ) : items.length === 0 ? (
          <Text size="sm" c="dimmed">
            No history events yet.
          </Text>
        ) : (
          <>
            {error ? (
              <Text size="sm" c="red" mb="xs">
                {error}
              </Text>
            ) : null}
            <ScrollArea h={620} type="auto">
              <Stack gap="sm">
                {items.map((item) => (
                  <Card withBorder key={item.id} p="sm">
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={4}>
                        <Group gap="xs">
                          <Badge color={categoryColor(item.category)} variant="light">
                            {item.category}
                          </Badge>
                          <Badge variant="outline">{scenarioLabel(item.scenario)}</Badge>
                        </Group>
                        <Text fw={600}>{item.title}</Text>
                        <Text size="sm" c="dimmed">
                          {item.message}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {formatTime(item.timestamp)}
                        </Text>
                      </Stack>
                      <Button
                        size="xs"
                        variant="subtle"
                        color="red"
                        onClick={() => void removeOne(item)}
                        disabled={actioning}
                      >
                        Delete
                      </Button>
                    </Group>
                  </Card>
                ))}
              </Stack>
            </ScrollArea>
          </>
        )}
      </Card>
    </Stack>
  );
}
