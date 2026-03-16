import { AppShell, Group, Loader, Stack, Tabs, Text, ThemeIcon, Title } from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { IconBooks } from "@tabler/icons-react";
import {
  getJobsSummary,
  getRuntimeStatus,
  getConfig,
  getDiff,
  saveConfig,
  validateConfig
} from "./api/client";
import type { JobsSummary, RuntimeStatusResponse } from "./api/client";
import ConfigEditor from "./components/ConfigEditor";
import Dashboard from "./components/Dashboard";
import DirectoryMapper from "./components/DirectoryMapper";
import LogsPanel from "./components/LogsPanel";
import type { ConfigModel, ConfigResponse, Issue } from "./types/config";

const cloneConfig = (value: ConfigModel): ConfigModel => JSON.parse(JSON.stringify(value));

const TAB_PATHS = {
  dashboard: "/dashboard",
  config: "/config",
  mapper: "/mapper",
  logs: "/logs"
} as const;

type TabKey = keyof typeof TAB_PATHS;

const PATH_TO_TAB: Record<string, TabKey> = {
  "/": "dashboard",
  "/dashboard": "dashboard",
  "/config": "config",
  "/mapper": "mapper",
  "/logs": "logs"
};

const normalizePath = (pathname: string): string => {
  if (!pathname || pathname === "/") {
    return "/";
  }
  return pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
};

const resolveTabFromPath = (pathname: string): TabKey => {
  const normalized = normalizePath(pathname);
  return PATH_TO_TAB[normalized] ?? "dashboard";
};

const resolvePathFromTab = (tab: string | null): string => {
  if (tab && tab in TAB_PATHS) {
    return TAB_PATHS[tab as TabKey];
  }
  return TAB_PATHS.dashboard;
};

export default function App() {
  const [response, setResponse] = useState<ConfigResponse | null>(null);
  const [draft, setDraft] = useState<ConfigModel | null>(null);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [diffText, setDiffText] = useState("");
  const [yamlPreview, setYamlPreview] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatusResponse | null>(null);
  const [jobsSummary, setJobsSummary] = useState<JobsSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>(() =>
    resolveTabFromPath(window.location.pathname)
  );

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
    if (activeTab !== "dashboard") {
      return;
    }

    let active = true;
    let inFlight = false;

    const loadRuntimeStatus = async () => {
      if (inFlight) {
        return;
      }
      inFlight = true;
      try {
        const [runtimeResult, jobsResult] = await Promise.all([
          getRuntimeStatus(),
          getJobsSummary()
        ]);
        if (active) {
          setRuntimeStatus(runtimeResult);
          setJobsSummary(jobsResult);
        }
      } catch (error) {
        void error;
      } finally {
        inFlight = false;
      }
    };

    void loadRuntimeStatus();
    const interval = window.setInterval(() => {
      void loadRuntimeStatus();
    }, 3000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [activeTab]);

  useEffect(() => {
    const syncFromPath = () => {
      const nextTab = resolveTabFromPath(window.location.pathname);
      setActiveTab(nextTab);

      const canonicalPath = resolvePathFromTab(nextTab);
      if (normalizePath(window.location.pathname) !== canonicalPath) {
        window.history.replaceState({}, "", canonicalPath);
      }
    };

    syncFromPath();
    window.addEventListener("popstate", syncFromPath);
    return () => {
      window.removeEventListener("popstate", syncFromPath);
    };
  }, []);

  const handleTabChange = (value: string | null) => {
    const nextTab = resolveTabFromPath(resolvePathFromTab(value));
    setActiveTab(nextTab);

    const nextPath = resolvePathFromTab(nextTab);
    if (normalizePath(window.location.pathname) !== nextPath) {
      window.history.pushState({}, "", nextPath);
    }
  };

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
    if (!draft) {
      return;
    }

    const saveResult = await saveConfig(draft);
    setIssues(saveResult.issues ?? []);
    if (!saveResult.saved) {
      return;
    }

    await reloadFromDisk();
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
        <Tabs value={activeTab} onChange={handleTabChange}>
          <Tabs.List>
            <Tabs.Tab value="dashboard">Dashboard</Tabs.Tab>
            <Tabs.Tab value="config">Config Editor</Tabs.Tab>
            <Tabs.Tab value="mapper">Directory Mapper</Tabs.Tab>
            <Tabs.Tab value="logs">Logs</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="dashboard" pt="md">
            {activeTab === "dashboard" && (
              <Dashboard
                hasUnsavedChanges={hasUnsavedChanges}
                runtimeStatus={runtimeStatus}
                jobsSummary={jobsSummary}
              />
            )}
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

          <Tabs.Panel value="logs" pt="md">
            {activeTab === "logs" && <LogsPanel />}
          </Tabs.Panel>
        </Tabs>
      </AppShell.Main>
    </AppShell>
  );
}
