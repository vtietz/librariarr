import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Tooltip,
  Title
} from "@mantine/core";
import { IconArrowsShuffle, IconCopy, IconFolderOpen, IconRefresh } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getDiscoveryWarnings,
  getFsRoots,
  getMappedDirectories,
  getMappedDirectoriesStreamUrl,
  runMaintenanceReconcile
} from "../api/client";
import DirectoryPickerModal from "./DirectoryPickerModal";

type MappedDirectory = {
  shadow_root: string;
  virtual_path: string;
  real_path: string;
  target_exists: boolean;
};

type PathCellProps = {
  value: string;
  onCopy: (value: string) => Promise<void>;
  onOpen: (value: string) => void;
};

const truncateMiddle = (value: string, maxLen: number = 54): string => {
  if (value.length <= maxLen) {
    return value;
  }
  const keep = maxLen - 3;
  const left = Math.ceil(keep / 2);
  const right = Math.floor(keep / 2);
  return `${value.slice(0, left)}...${value.slice(value.length - right)}`;
};

function PathCell({ value, onCopy, onOpen }: PathCellProps) {
  return (
    <Group gap="xs" wrap="nowrap">
      <Text
        size="sm"
        title={value}
        style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
      >
        {truncateMiddle(value)}
      </Text>
      <Tooltip label="Copy path">
        <ActionIcon
          size="sm"
          variant="light"
          aria-label="Copy path"
          onClick={() => void onCopy(value)}
        >
          <IconCopy size={14} />
        </ActionIcon>
      </Tooltip>
      <Tooltip label="Open path">
        <ActionIcon
          size="sm"
          variant="light"
          aria-label="Open path"
          onClick={() => onOpen(value)}
        >
          <IconFolderOpen size={14} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}

export default function DirectoryMapper() {
  const [mappedDirectories, setMappedDirectories] = useState<MappedDirectory[]>([]);
  const [mappedSearch, setMappedSearch] = useState("");
  const [debouncedMappedSearch, setDebouncedMappedSearch] = useState("");
  const [mappedRootFilter, setMappedRootFilter] = useState<string>("all");
  const [mappedRoots, setMappedRoots] = useState<string[]>([]);
  const [mappedTruncated, setMappedTruncated] = useState(false);
  const [cacheEntriesTotal, setCacheEntriesTotal] = useState(0);
  const [isReloading, setIsReloading] = useState(false);
  const [isReconciling, setIsReconciling] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cacheBuilding, setCacheBuilding] = useState(false);
  const [cacheReady, setCacheReady] = useState(false);
  const [cacheUpdatedAtMs, setCacheUpdatedAtMs] = useState<number | null>(null);
  const [fsRoots, setFsRoots] = useState<string[]>([]);
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [discoveryWarnings, setDiscoveryWarnings] = useState<Awaited<
    ReturnType<typeof getDiscoveryWarnings>
  > | null>(null);

  const loadMappedDirectories = useCallback(async () => {
    setIsReloading(true);
    setLoadError(null);
    try {
      const result = await getMappedDirectories({
        search: debouncedMappedSearch.trim() || undefined,
        shadowRoot: mappedRootFilter === "all" ? undefined : mappedRootFilter,
        limit: 5000,
        timeoutMs: 90000
      });
      const sortedItems = [...result.items].sort((left, right) => {
        const rootCompare = left.shadow_root.localeCompare(right.shadow_root);
        if (rootCompare !== 0) {
          return rootCompare;
        }
        const virtualCompare = left.virtual_path.localeCompare(right.virtual_path);
        if (virtualCompare !== 0) {
          return virtualCompare;
        }
        return left.real_path.localeCompare(right.real_path);
      });

      setMappedDirectories(sortedItems);
      setMappedRoots([...result.shadow_roots].sort((left, right) => left.localeCompare(right)));
      setMappedTruncated(result.truncated);
      setCacheBuilding(result.cache?.building ?? false);
      setCacheReady(result.cache?.ready ?? false);
      setCacheUpdatedAtMs(result.cache?.updated_at_ms ?? null);
      setCacheEntriesTotal(result.cache?.entries_total ?? sortedItems.length);

      if ((result.cache?.last_error ?? null) && sortedItems.length === 0) {
        setLoadError(result.cache?.last_error ?? "Failed to load mapped directories.");
      }
    } catch (error: unknown) {
      const detail =
        typeof error === "object" &&
        error !== null &&
        "response" in error &&
        typeof (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail ===
          "string"
          ? ((error as { response: { data: { detail: string } } }).response.data.detail ?? null)
          : null;
      const timedOut =
        typeof error === "object" &&
        error !== null &&
        "code" in error &&
        (error as { code?: string }).code === "ECONNABORTED";

      setLoadError(
        detail ||
          (timedOut
            ? "Snapshot request timed out. The backend may still be rebuilding/scanning or serializing a large index; wait briefly or trigger a full reconcile."
            : "Failed to load mapped directories.")
      );
      setMappedDirectories([]);
      setMappedRoots([]);
      setMappedTruncated(false);
      setCacheBuilding(false);
      setCacheReady(false);
      setCacheUpdatedAtMs(null);
      setCacheEntriesTotal(0);
    } finally {
      setIsReloading(false);
    }
  }, [debouncedMappedSearch, mappedRootFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedMappedSearch(mappedSearch);
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [mappedSearch]);

  useEffect(() => {
    void loadMappedDirectories();
  }, [loadMappedDirectories]);

  useEffect(() => {
    void (async () => {
      try {
        setFsRoots(await getFsRoots());
      } catch {
        setFsRoots([]);
      }
    })();
  }, []);

  useEffect(() => {
    let active = true;

    const loadWarnings = async () => {
      try {
        const payload = await getDiscoveryWarnings({ limit: 200 });
        if (active) {
          setDiscoveryWarnings(payload);
        }
      } catch {
        if (active) {
          setDiscoveryWarnings(null);
        }
      }
    };

    void loadWarnings();
    const interval = window.setInterval(() => {
      void loadWarnings();
    }, 5000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const source = new EventSource(getMappedDirectoriesStreamUrl({ intervalMs: 1000 }));

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as {
          changed?: boolean;
          cache_building?: boolean;
          cache_ready?: boolean;
        };
        if (typeof payload.cache_building === "boolean") {
          setCacheBuilding(payload.cache_building);
        }
        if (typeof payload.cache_ready === "boolean") {
          setCacheReady(payload.cache_ready);
        }
        if (payload.changed) {
          void loadMappedDirectories();
        }
      } catch {
        /* malformed SSE event — keep current list */
      }
    };

    return () => {
      source.close();
    };
  }, [loadMappedDirectories]);

  const mappedRootOptions = useMemo(
    () => [
      { label: "All shadow roots", value: "all" },
      ...mappedRoots.map((root) => ({ label: root, value: root }))
    ],
    [mappedRoots]
  );

  const duplicatePrimaryPaths = useMemo(() => {
    const paths = new Set<string>();
    for (const item of discoveryWarnings?.duplicate_movie_candidates ?? []) {
      paths.add(item.primary_path);
    }
    return paths;
  }, [discoveryWarnings]);

  const excludedByDuplicate = useMemo(() => {
    const byPrimary = new Map<string, number>();
    for (const item of discoveryWarnings?.duplicate_movie_candidates ?? []) {
      if (!item.contains_excluded) {
        continue;
      }
      byPrimary.set(item.primary_path, item.duplicate_paths.length);
    }
    return byPrimary;
  }, [discoveryWarnings]);

  const cacheStatusText = useMemo(() => {
    if (cacheBuilding && !cacheReady) {
      return "Indexing in progress";
    }
    if (!cacheReady) {
      return "Index not ready";
    }
    if (typeof cacheUpdatedAtMs !== "number") {
      return "Index ready";
    }
    const elapsedSec = Math.max(0, Math.floor((Date.now() - cacheUpdatedAtMs) / 1000));
    if (elapsedSec < 60) {
      return `Index ready · updated ${elapsedSec}s ago`;
    }
    const elapsedMin = Math.floor(elapsedSec / 60);
    if (elapsedMin < 60) {
      return `Index ready · updated ${elapsedMin}m ago`;
    }
    const elapsedHours = Math.floor(elapsedMin / 60);
    return `Index ready · updated ${elapsedHours}h ago`;
  }, [cacheBuilding, cacheReady, cacheUpdatedAtMs]);

  const copyToClipboard = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      /* ignore clipboard failures */
    }
  };

  const queueReconcile = async () => {
    setIsReconciling(true);
    try {
      await runMaintenanceReconcile();
    } finally {
      setIsReconciling(false);
    }
  };

  return (
    <Stack>
      <Title order={3}>Directory Mapper</Title>

      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Text fw={600}>Mapped Directories (Virtual vs Real)</Text>
            <Group gap="sm">
              <Text size="sm" c="dimmed">
                Showing {mappedDirectories.length} of {cacheEntriesTotal}
                {mappedTruncated ? " (list truncated)" : ""}
              </Text>
              <Tooltip label="Refresh snapshot now">
                <ActionIcon
                  variant="light"
                  size="md"
                  onClick={() => void loadMappedDirectories()}
                  disabled={isReloading}
                  aria-label="Refresh mapped directories"
                >
                  <IconRefresh size={16} />
                </ActionIcon>
              </Tooltip>
              <Button
                variant="light"
                size="xs"
                leftSection={<IconArrowsShuffle size={14} />}
                onClick={() => void queueReconcile()}
                loading={isReconciling}
              >
                Reconcile whole library
              </Button>
            </Group>
          </Group>

          <Text size="xs" c="dimmed">{cacheStatusText}</Text>
          <Text size="xs" c="dimmed">
            The list is built from in-memory cache and updates automatically. Refresh only forces an
            immediate API fetch.
          </Text>

          {(discoveryWarnings?.summary.duplicate_movie_candidates ?? 0) > 0 && (
            <Text size="sm" c="yellow.8">
              ⚠ {discoveryWarnings?.summary.duplicate_movie_candidates ?? 0} potential duplicate
              movie keys detected in source folders
            </Text>
          )}

          {(discoveryWarnings?.summary.excluded_movie_candidates ?? 0) > 0 && (
            <Text size="sm" c="yellow.8">
              ⚠ {discoveryWarnings?.summary.excluded_movie_candidates ?? 0} movie folders ignored
              by paths.exclude_paths
            </Text>
          )}

          <Group grow>
            <TextInput
              label="Search"
              placeholder="Search virtual or real path"
              value={mappedSearch}
              onChange={(event) => setMappedSearch(event.currentTarget.value)}
            />
            <Select
              label="Shadow root filter"
              data={mappedRootOptions}
              value={mappedRootFilter}
              onChange={(value: string | null) => setMappedRootFilter(value ?? "all")}
            />
          </Group>

          <Table striped withRowBorders={false} style={{ tableLayout: "fixed", width: "100%" }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Shadow Root</Table.Th>
                <Table.Th>Virtual Path</Table.Th>
                <Table.Th>Real Path</Table.Th>
                <Table.Th>Status</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {loadError ? (
                <Table.Tr>
                  <Table.Td colSpan={4}>
                    <Text size="sm" c="red">
                      {loadError}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : mappedDirectories.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={4}>
                    <Text size="sm" c="dimmed">
                      {cacheBuilding && !cacheReady
                        ? "Building in-memory directory index… wait a few seconds."
                        : "No mapped directories match the current search/filter."}
                    </Text>
                  </Table.Td>
                </Table.Tr>
              ) : (
                mappedDirectories.map((mapped) => (
                  <Table.Tr key={`${mapped.shadow_root}:${mapped.virtual_path}`}>
                    <Table.Td style={{ width: "24%", minWidth: 0 }}>
                      <PathCell
                        value={mapped.shadow_root}
                        onCopy={copyToClipboard}
                        onOpen={setBrowsePath}
                      />
                    </Table.Td>
                    <Table.Td style={{ width: "30%", minWidth: 0 }}>
                      <PathCell
                        value={mapped.virtual_path}
                        onCopy={copyToClipboard}
                        onOpen={setBrowsePath}
                      />
                    </Table.Td>
                    <Table.Td style={{ width: "30%", minWidth: 0 }}>
                      <PathCell
                        value={mapped.real_path}
                        onCopy={copyToClipboard}
                        onOpen={setBrowsePath}
                      />
                    </Table.Td>
                    <Table.Td style={{ width: "16%", minWidth: 0 }}>
                      <Group gap={6}>
                        <Badge color={mapped.target_exists ? "green" : "red"}>
                          {mapped.target_exists ? "target exists" : "missing target"}
                        </Badge>
                        {duplicatePrimaryPaths.has(mapped.real_path) && (
                          <Badge color="yellow">⚠ duplicate candidate</Badge>
                        )}
                        {(excludedByDuplicate.get(mapped.real_path) ?? 0) > 0 && (
                          <Badge color="orange">
                            excluded alt paths: {excludedByDuplicate.get(mapped.real_path)}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                  </Table.Tr>
                ))
              )}
            </Table.Tbody>
          </Table>

          <DirectoryPickerModal
            opened={browsePath !== null}
            title="Browse directory"
            roots={fsRoots}
            initialPath={browsePath ?? ""}
            onClose={() => setBrowsePath(null)}
            mode="browse"
          />
        </Stack>
      </Card>
    </Stack>
  );
}
