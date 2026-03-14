import { AppShell, Group, Loader, Stack, Tabs, Text, ThemeIcon, Title } from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { IconBooks } from "@tabler/icons-react";
import {
  getRuntimeStatus,
  getConfig,
  getDiff,
  saveConfig,
  validateConfig
} from "./api/client";
import type { RuntimeStatusResponse } from "./api/client";
import ConfigEditor from "./components/ConfigEditor";
import Dashboard from "./components/Dashboard";
import DiagnosticsPanel from "./components/DiagnosticsPanel";
import DirectoryMapper from "./components/DirectoryMapper";
import LogsPanel from "./components/LogsPanel";
import type { ConfigModel, ConfigResponse, Issue } from "./types/config";

const cloneConfig = (value: ConfigModel): ConfigModel => JSON.parse(JSON.stringify(value));

export default function App() {
  const [response, setResponse] = useState<ConfigResponse | null>(null);
  const [draft, setDraft] = useState<ConfigModel | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [diffText, setDiffText] = useState("");
  const [yamlPreview, setYamlPreview] = useState("");
  const [radarrStatus, setRadarrStatus] = useState<"idle" | "ok" | "warning" | "disabled">("idle");
  const [sonarrStatus, setSonarrStatus] = useState<"idle" | "ok" | "warning" | "disabled">("idle");
  const [lastDryRunSummary, setLastDryRunSummary] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatusResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("dashboard");

  const parseLoadError = (error: unknown): string => {
    if (typeof error !== "object" || error === null) {
      return "Unable to load configuration from API.";
    }

    const maybeResponse = (error as { response?: { data?: unknown } }).response;
    const detail =
      maybeResponse &&
      typeof maybeResponse.data === "object" &&
      maybeResponse.data !== null &&
      "detail" in maybeResponse.data
        ? (maybeResponse.data as { detail?: unknown }).detail
        : undefined;

    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }

    return "Unable to load configuration from API.";
  };

  const reloadFromDisk = useCallback(async () => {
    try {
      const config = await getConfig("disk");
      setResponse(config);
      setDraft(cloneConfig(config.config));
      setIssues([]);
      setDiffText("");
      setYamlPreview(config.yaml);
      setLoadError(null);
    } catch (error: unknown) {
      setLoadError(parseLoadError(error));
    }
  }, []);

  useEffect(() => {
    void reloadFromDisk();
  }, [reloadFromDisk]);

  useEffect(() => {
    let active = true;

    const loadRuntimeStatus = async () => {
      try {
        const result = await getRuntimeStatus();
        if (active) {
          setRuntimeStatus(result);
        }
      } catch {
        if (active) {
          setRuntimeStatus(null);
        }
      }
    };

    void loadRuntimeStatus();
    const interval = window.setInterval(() => {
      void loadRuntimeStatus();
    }, 2000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const hasUnsavedChanges = useMemo(() => {
    if (!response || !draft) {
      return false;
    }
    return JSON.stringify(response.config) !== JSON.stringify(draft);
  }, [response, draft]);

  const handleValidate = async () => {
    if (!draft) {
      return;
    }
    const result = await validateConfig(draft);
    setIssues(result.issues ?? []);
    if (result.valid) {
      const draftConfig = await getConfig("draft");
      setYamlPreview(draftConfig.yaml);
    }
  };

  const handleSave = async () => {
    if (!draft) {
      return;
    }
    const result = await saveConfig(draft);
    setIssues(result.issues ?? []);
    if (result.saved) {
      await reloadFromDisk();
    }
  };

  const handleDiff = async () => {
    const result = await getDiff();
    setDiffText(result.diff);
  };

  if (loadError) {
    return (
      <Stack align="center" justify="center" h="100vh" gap="xs">
        <Text c="red" fw={600}>
          Failed to load LibrariArr config
        </Text>
        <Text c="dimmed" size="sm">
          {loadError}
        </Text>
        <Text c="dimmed" size="sm">
          Run `./run.sh setup` to create a valid config file if missing.
        </Text>
      </Stack>
    );
  }

  if (!response || !draft) {
    return (
      <Stack align="center" justify="center" h="100vh">
        <Loader />
        <Text c="dimmed">Loading LibrariArr UI...</Text>
      </Stack>
    );
  }

  return (
    <AppShell padding="md" header={{ height: 62 }}>
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="xs">
            <ThemeIcon variant="light" size="lg" radius="md">
              <IconBooks size={18} />
            </ThemeIcon>
            <Title order={3}>LibrariArr Admin</Title>
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Tabs defaultValue="dashboard" onChange={(value) => setActiveTab(value ?? "dashboard")}>
          <Tabs.List>
            <Tabs.Tab value="dashboard">Dashboard</Tabs.Tab>
            <Tabs.Tab value="config">Config Editor</Tabs.Tab>
            <Tabs.Tab value="mapper">Directory Mapper</Tabs.Tab>
            <Tabs.Tab value="diagnostics">Diagnostics</Tabs.Tab>
            <Tabs.Tab value="logs">Logs</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="dashboard" pt="md">
            <Dashboard
              radarrStatus={radarrStatus}
              sonarrStatus={sonarrStatus}
              hasUnsavedChanges={hasUnsavedChanges}
              lastDryRunSummary={lastDryRunSummary}
              runtimeStatus={runtimeStatus}
            />
          </Tabs.Panel>

          <Tabs.Panel value="config" pt="md">
            <ConfigEditor
              draft={draft}
              hasUnsavedChanges={hasUnsavedChanges}
              issues={issues}
              yamlPreview={yamlPreview}
              onValidate={handleValidate}
              onSave={handleSave}
              onLoadDiff={handleDiff}
              diffText={diffText}
              onChange={setDraft}
            />
          </Tabs.Panel>

          <Tabs.Panel value="mapper" pt="md">
            {activeTab === "mapper" && <DirectoryMapper />}
          </Tabs.Panel>

          <Tabs.Panel value="diagnostics" pt="md">
            <DiagnosticsPanel
              draft={draft}
              onDryRunSummary={setLastDryRunSummary}
              onStatuses={(radarr, sonarr) => {
                if (radarr !== "idle") {
                  setRadarrStatus(radarr as "ok" | "warning" | "disabled");
                }
                if (sonarr !== "idle") {
                  setSonarrStatus(sonarr as "ok" | "warning" | "disabled");
                }
              }}
            />
          </Tabs.Panel>

          <Tabs.Panel value="logs" pt="md">
            {activeTab === "logs" && <LogsPanel />}
          </Tabs.Panel>
        </Tabs>
      </AppShell.Main>
    </AppShell>
  );
}
