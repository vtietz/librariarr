import {
  ActionIcon,
  Box,
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
import { useViewportSize } from "@mantine/hooks";
import { IconArrowsShuffle, IconRefresh } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getDiscoveryWarnings,
  getFsRoots,
  getMappedDirectories,
  getMappedDirectoriesStreamUrl,
  refreshMappedDirectories,
  runMaintenanceReconcile,
  waitForJobCompletion
} from "../api/client";
import DirectoryPickerModal from "./DirectoryPickerModal";
import MappedRows, { type MappedDirectory } from "./DirectoryMapperRows";

export default function DirectoryMapper() {
  const ROW_HEIGHT = 44;

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
  const [scrollTop, setScrollTop] = useState(0);
  const [discoveryWarnings, setDiscoveryWarnings] = useState<Awaited<
    ReturnType<typeof getDiscoveryWarnings>
  > | null>(null);
  const { height: viewportHeightPx } = useViewportSize();
  const tableViewportRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);

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

  const loadDiscoveryWarnings = useCallback(async () => {
    try {
      const payload = await getDiscoveryWarnings({ limit: 200 });
      setDiscoveryWarnings(payload);
    } catch {
      setDiscoveryWarnings(null);
    }
  }, []);

  useEffect(() => {
    void loadDiscoveryWarnings();
  }, [loadDiscoveryWarnings]);

  useEffect(() => {
    const source = new EventSource(getMappedDirectoriesStreamUrl({ intervalMs: 2000 }));

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
          void loadDiscoveryWarnings();
        }
      } catch {
        /* malformed SSE event — keep current list */
      }
    };

    return () => {
      source.close();
    };
  }, [loadMappedDirectories, loadDiscoveryWarnings]);

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
    if (isReconciling) {
      return "Reconciling whole library...";
    }
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
  }, [cacheBuilding, cacheReady, cacheUpdatedAtMs, isReconciling]);

  const copyToClipboard = useCallback(async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      /* ignore clipboard failures */
    }
  }, []);

  const openBrowsePath = useCallback((value: string) => {
    setBrowsePath(value);
  }, []);

  const virtualizedViewportHeight = useMemo(
    () => Math.max(320, Math.min(760, viewportHeightPx - 360)),
    [viewportHeightPx]
  );

  const overscanRows = useMemo(
    () => Math.max(10, Math.ceil(virtualizedViewportHeight / ROW_HEIGHT)),
    [virtualizedViewportHeight]
  );

  const virtualizationEnabled = mappedDirectories.length > 200;

  const visibleRange = useMemo(() => {
    if (!virtualizationEnabled) {
      return { startIndex: 0, endIndex: mappedDirectories.length };
    }
    const startIndex = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - overscanRows);
    const visibleRows = Math.ceil(virtualizedViewportHeight / ROW_HEIGHT) + overscanRows * 2;
    const endIndex = Math.min(mappedDirectories.length, startIndex + visibleRows);
    return { startIndex, endIndex };
  }, [mappedDirectories.length, overscanRows, scrollTop, virtualizedViewportHeight, virtualizationEnabled]);

  const visibleDirectories = useMemo(
    () => mappedDirectories.slice(visibleRange.startIndex, visibleRange.endIndex),
    [mappedDirectories, visibleRange.endIndex, visibleRange.startIndex]
  );

  const topSpacerHeight = virtualizationEnabled ? visibleRange.startIndex * ROW_HEIGHT : 0;
  const bottomSpacerHeight = virtualizationEnabled
    ? Math.max(0, (mappedDirectories.length - visibleRange.endIndex) * ROW_HEIGHT)
    : 0;

  useEffect(() => {
    setScrollTop(0);
    if (tableViewportRef.current) {
      tableViewportRef.current.scrollTop = 0;
    }
  }, [mappedRootFilter, debouncedMappedSearch]);

  useEffect(() => {
    return () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    };
  }, []);

  const handleViewportScroll = useCallback(
    (nextScrollTop: number) => {
      if (!virtualizationEnabled) {
        return;
      }
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
      scrollFrameRef.current = window.requestAnimationFrame(() => {
        setScrollTop(nextScrollTop);
        scrollFrameRef.current = null;
      });
    },
    [virtualizationEnabled]
  );

  const forceRefreshCache = async () => {
    setIsReloading(true);
    setLoadError(null);
    try {
      await refreshMappedDirectories();
      await loadMappedDirectories();
      await loadDiscoveryWarnings();
    } catch {
      setLoadError("Failed to refresh the mapped directories cache.");
    } finally {
      setIsReloading(false);
    }
  };

  const queueReconcile = async () => {
    setIsReconciling(true);
    setLoadError(null);
    try {
      const scheduled = await runMaintenanceReconcile();
      if (!scheduled.job_id) {
        throw new Error("Reconcile job was not scheduled.");
      }
      await waitForJobCompletion(scheduled.job_id);
      await loadMappedDirectories();
      await loadDiscoveryWarnings();
    } catch (error) {
      setLoadError(
        error instanceof Error
          ? `Reconcile failed: ${error.message}`
          : "Reconcile failed unexpectedly."
      );
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
              <Tooltip label="Force full rescan of shadow roots">
                <ActionIcon
                  variant="light"
                  size="md"
                  onClick={() => void forceRefreshCache()}
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
            The cache updates automatically after each reconcile. Use the refresh button to force a
            full rescan of shadow roots.
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

          <Table withRowBorders={false} style={{ tableLayout: "fixed", width: "100%" }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: "46%" }}>Virtual Path</Table.Th>
                <Table.Th style={{ width: "46%" }}>Real Path</Table.Th>
                <Table.Th style={{ width: "8%" }}>Status</Table.Th>
              </Table.Tr>
            </Table.Thead>
          </Table>

          <Box
            ref={tableViewportRef}
            style={{
              maxHeight: virtualizedViewportHeight,
              overflowY: "auto"
            }}
            onScroll={(event) => {
              handleViewportScroll(event.currentTarget.scrollTop);
            }}
          >
            <Table withRowBorders={false} style={{ tableLayout: "fixed", width: "100%" }}>
              <Table.Tbody>
                {loadError ? (
                  <Table.Tr>
                    <Table.Td colSpan={3}>
                      <Text size="sm" c="red">
                        {loadError}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : mappedDirectories.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={3}>
                      <Text size="sm" c="dimmed">
                        {cacheBuilding && !cacheReady
                          ? "Building in-memory directory index… wait a few seconds."
                          : mappedSearch.trim() || mappedRootFilter !== "all"
                            ? "No mapped directories match the current search/filter."
                            : "No mapped directories indexed yet. Run 'Reconcile whole library' and verify root mappings if this stays empty."}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  <>
                    {topSpacerHeight > 0 && (
                      <Table.Tr>
                        <Table.Td colSpan={3} style={{ height: topSpacerHeight, padding: 0 }} />
                      </Table.Tr>
                    )}
                    <MappedRows
                      visibleDirectories={visibleDirectories}
                      duplicatePrimaryPaths={duplicatePrimaryPaths}
                      excludedByDuplicate={excludedByDuplicate}
                      onCopy={copyToClipboard}
                      onOpen={openBrowsePath}
                    />
                    {bottomSpacerHeight > 0 && (
                      <Table.Tr>
                        <Table.Td colSpan={3} style={{ height: bottomSpacerHeight, padding: 0 }} />
                      </Table.Tr>
                    )}
                  </>
                )}
              </Table.Tbody>
            </Table>
          </Box>

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
