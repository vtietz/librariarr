import { AppShell, Badge, Group, Tabs, ThemeIcon, Title } from "@mantine/core";
import { IconBooks } from "@tabler/icons-react";
import { useCallback, useEffect, useState } from "react";
import type { StatusResponse, UnmatchedResponse } from "./api/client";
import { getStatus, getUnmatched, triggerReconcile } from "./api/client";
import ConfigPanel from "./components/ConfigPanel";
import LogsPanel from "./components/LogsPanel";
import StatusPanel from "./components/StatusPanel";
import UnmatchedPanel from "./components/UnmatchedPanel";

export default function App() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [unmatched, setUnmatched] = useState<UnmatchedResponse>({
    unmatched: [],
    as_of: null
  });

  const refresh = useCallback(() => {
    getStatus().then(setStatus).catch(() => undefined);
    getUnmatched().then(setUnmatched).catch(() => undefined);
  }, []);

  const runFullPass = useCallback(() => {
    triggerReconcile("full").then(refresh).catch(() => undefined);
  }, [refresh]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <ThemeIcon variant="light" size="lg">
              <IconBooks size={20} />
            </ThemeIcon>
            <Title order={4}>LibrariArr</Title>
          </Group>
          {status && (
            <Badge color={status.running ? "yellow" : "green"}>
              {status.running ? `running: ${status.running_scope}` : "idle"}
            </Badge>
          )}
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Tabs defaultValue="status" keepMounted={false}>
          <Tabs.List mb="md">
            <Tabs.Tab value="status">Status</Tabs.Tab>
            <Tabs.Tab value="unmatched">
              Unmatched{unmatched.unmatched.length > 0 ? ` (${unmatched.unmatched.length})` : ""}
            </Tabs.Tab>
            <Tabs.Tab value="config">Config</Tabs.Tab>
            <Tabs.Tab value="logs">Logs</Tabs.Tab>
          </Tabs.List>
          <Tabs.Panel value="status">
            <StatusPanel status={status} onRefresh={refresh} />
          </Tabs.Panel>
          <Tabs.Panel value="unmatched">
            <UnmatchedPanel
              unmatched={unmatched.unmatched}
              asOf={unmatched.as_of}
              onRunFullPass={runFullPass}
              onRefresh={refresh}
            />
          </Tabs.Panel>
          <Tabs.Panel value="config">
            <ConfigPanel />
          </Tabs.Panel>
          <Tabs.Panel value="logs">
            <LogsPanel />
          </Tabs.Panel>
        </Tabs>
      </AppShell.Main>
    </AppShell>
  );
}
