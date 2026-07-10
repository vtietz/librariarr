import { Badge, Code, Group, Stack, Switch, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import type { LogEntry } from "../api/client";
import { getLogs } from "../api/client";

const LEVEL_COLORS: Record<string, string> = {
  error: "red",
  warning: "yellow",
  info: "blue",
  debug: "gray"
};

export default function LogsPanel() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [autoRefresh, setAutoRefresh] = useState(true);

  useEffect(() => {
    let active = true;
    const load = () =>
      getLogs(300)
        .then((data) => {
          if (active) setEntries(data);
        })
        .catch(() => undefined);
    load();
    if (!autoRefresh) return () => void (active = false);
    const timer = setInterval(load, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [autoRefresh]);

  return (
    <Stack gap="sm">
      <Group>
        <Switch
          checked={autoRefresh}
          onChange={(event) => setAutoRefresh(event.currentTarget.checked)}
          label="Auto-refresh"
          size="sm"
        />
        <Text size="sm" c="dimmed">
          newest first
        </Text>
      </Group>
      <Stack gap={2}>
        {entries.map((entry) => (
          <Group key={entry.seq} gap="xs" wrap="nowrap" align="flex-start">
            <Badge
              size="xs"
              color={LEVEL_COLORS[entry.level?.toLowerCase()] ?? "gray"}
              style={{ minWidth: 60 }}
            >
              {entry.level}
            </Badge>
            <Code block style={{ flex: 1, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
              {entry.line}
            </Code>
          </Group>
        ))}
      </Stack>
    </Stack>
  );
}
