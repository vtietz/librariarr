import {
  ActionIcon,
  Box,
  Button,
  Card,
  Group,
  Loader,
  MultiSelect,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
  Title
} from "@mantine/core";
import { IconArrowsShuffle, IconRefresh } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type DiscoveryWarningsResponse,
  getDiscoveryWarnings,
  getFsRoots,
  getMappedDirectories,
  getMappedDirectoriesStreamUrl,
  refreshMappedDirectories
} from "../api/client";
import DeleteShadowConfirmModal from "./DeleteShadowConfirmModal";
import DirectoryPickerModal from "./DirectoryPickerModal";
import MappedRows, { type MappedDirectory } from "./DirectoryMapperRows";
import {
  mappedCacheStatusText,
  mappedDirectoriesErrorMessage,
  sortMappedDirectories
} from "./directoryMapperLoadUtils";
import { useScopedArrEnrichment } from "./useScopedArrEnrichment";
import { MAPPER_STATUS_FILTER_OPTIONS, useMapperRowsView } from "./useMapperRowsView";
import { useReconcileActions } from "./useReconcileActions";
import { useRadarrRefreshAction } from "./useRadarrRefreshAction";
import { useDeleteShadowAction } from "./useDeleteShadowAction";
import { useDiscoveryWarningSets } from "./useDiscoveryWarningSets";

export default function DirectoryMapper() {
  const [mappedDirectories, setMappedDirectories] = useState<MappedDirectory[]>([]);
  const [mappedSearch, setMappedSearch] = useState("");
  const [debouncedMappedSearch, setDebouncedMappedSearch] = useState("");
  const [isSearchTransitioning, setIsSearchTransitioning] = useState(false);
  const [mappedRootFilter, setMappedRootFilter] = useState<string>("all");
  const [mappedRoots, setMappedRoots] = useState<string[]>([]);
  const [mappedTruncated, setMappedTruncated] = useState(false);
  const [cacheEntriesTotal, setCacheEntriesTotal] = useState(0);
  const [isReloading, setIsReloading] = useState(false);
  const [isReconciling, setIsReconciling] = useState(false);
  const [reconcilingPath, setReconcilingPath] = useState<string | null>(null);
  const [refreshingMovieId, setRefreshingMovieId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [cacheBuilding, setCacheBuilding] = useState(false);
  const [cacheReady, setCacheReady] = useState(false);
  const [cacheUpdatedAtMs, setCacheUpdatedAtMs] = useState<number | null>(null);
  const [isArrEnrichmentLoading, setIsArrEnrichmentLoading] = useState(false);
  const [fsRoots, setFsRoots] = useState<string[]>([]);
  const [browsePath, setBrowsePath] = useState<string | null>(null);
  const [discoveryWarnings, setDiscoveryWarnings] =
    useState<DiscoveryWarningsResponse | null>(null);
  const mappedLoadVersionRef = useRef(0);

  const applyMappedSnapshot = useCallback(
    (result: Awaited<ReturnType<typeof getMappedDirectories>>) => {
      const sortedItems = sortMappedDirectories(result.items);
      setMappedDirectories(sortedItems);
      setMappedRoots([...result.shadow_roots].sort((left, right) => left.localeCompare(right)));
      setMappedTruncated(result.truncated);
      setCacheBuilding(result.cache?.building ?? false);
      setCacheReady(result.cache?.ready ?? false);
      setCacheUpdatedAtMs(result.cache?.updated_at_ms ?? null);
      setCacheEntriesTotal(result.cache?.entries_total ?? sortedItems.length);
      return sortedItems;
    },
    []
  );

  const loadMappedDirectories = useCallback(async () => {
    setIsReloading(true);
    setLoadError(null);
    const loadVersion = mappedLoadVersionRef.current + 1;
    mappedLoadVersionRef.current = loadVersion;
    const searchParam = debouncedMappedSearch.trim();
    const shadowRootParam = mappedRootFilter !== "all" ? mappedRootFilter : undefined;
    try {
      const baseResult = await getMappedDirectories({
        search: searchParam || undefined,
        shadowRoot: shadowRootParam,
        limit: 5000,
        includeArrState: false,
        timeoutMs: 30000
      });
      if (mappedLoadVersionRef.current !== loadVersion) {
        return;
      }
      const sortedBaseItems = applyMappedSnapshot(baseResult);
      if ((baseResult.cache?.last_error ?? null) && sortedBaseItems.length === 0) {
        setLoadError(baseResult.cache?.last_error ?? "Failed to load mapped directories.");
      }
    } catch (error: unknown) {
      if (mappedLoadVersionRef.current !== loadVersion) {
        return;
      }
      setLoadError(mappedDirectoriesErrorMessage(error));
      setMappedDirectories([]);
      setMappedRoots([]);
      setMappedTruncated(false);
      setCacheBuilding(false);
      setCacheReady(false);
      setCacheUpdatedAtMs(null);
      setCacheEntriesTotal(0);
    } finally {
      if (mappedLoadVersionRef.current === loadVersion) {
        setIsReloading(false);
      }
    }
  }, [applyMappedSnapshot, debouncedMappedSearch, mappedRootFilter]);

  useEffect(() => {
    if (mappedSearch === debouncedMappedSearch) {
      return;
    }
    setIsSearchTransitioning(true);
    const timer = window.setTimeout(() => {
      setDebouncedMappedSearch(mappedSearch);
      setIsSearchTransitioning(false);
    }, 300);
    return () => {
      window.clearTimeout(timer);
    };
  }, [debouncedMappedSearch, mappedSearch]);

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
      { label: "All library roots and series shadow roots", value: "all" },
      ...mappedRoots.map((root) => ({ label: root, value: root }))
    ],
    [mappedRoots]
  );

  const locallyFilteredDirectories = useMemo(() => {
    const loweredSearch = debouncedMappedSearch.trim().toLowerCase();
    return mappedDirectories.filter((item) => {
      if (mappedRootFilter !== "all" && item.shadow_root !== mappedRootFilter) {
        return false;
      }
      if (!loweredSearch) {
        return true;
      }
      return (
        item.virtual_path.toLowerCase().includes(loweredSearch) ||
        item.real_path.toLowerCase().includes(loweredSearch)
      );
    });
  }, [debouncedMappedSearch, mappedDirectories, mappedRootFilter]);

  const searchVisibleDirectories = useMemo(
    () => (isSearchTransitioning ? [] : locallyFilteredDirectories),
    [isSearchTransitioning, locallyFilteredDirectories]
  );

  const { duplicatePrimaryPaths, excludedByDuplicate, duplicatePathSet, excludedPathSet } =
    useDiscoveryWarningSets(discoveryWarnings);

  const {
    activeStatusFilters,
    filteredDirectories,
    visibleDirectories,
    hasMoreRows,
    loadMoreRef,
    setStatusFilters
  } = useMapperRowsView(searchVisibleDirectories);
  const arrEnrichmentCandidates = useMemo(() => {
    return visibleDirectories.length > 0 ? visibleDirectories : searchVisibleDirectories.slice(0, 200);
  }, [searchVisibleDirectories, visibleDirectories]);

  useScopedArrEnrichment({
    candidates: arrEnrichmentCandidates,
    search: debouncedMappedSearch,
    mappedRootFilter,
    mappedLoadVersionRef,
    setMappedDirectories,
    setCacheBuilding,
    setCacheReady,
    setCacheUpdatedAtMs,
    setCacheEntriesTotal,
    setArrEnrichmentLoading: setIsArrEnrichmentLoading
  });

  const isSearchLoading = isSearchTransitioning || isReloading;

  const cacheStatusText = mappedCacheStatusText({
    reconcilingPath,
    isReconciling,
    cacheBuilding,
    cacheReady,
    cacheUpdatedAtMs
  });
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

  const { queueReconcile, reconcilePath, recentlyReconciledPath } = useReconcileActions({
    setIsReconciling,
    setReconcilingPath,
    setLoadError,
    setMappedDirectories,
    loadMappedDirectories,
    loadDiscoveryWarnings
  });

  const refreshMovieInRadarr = useRadarrRefreshAction({
    setRefreshingMovieId,
    setLoadError,
    loadMappedDirectories
  });

  const { deletingPath, pendingDeletePath, requestDelete, cancelDelete, confirmDelete } = useDeleteShadowAction({
    setLoadError,
    setMappedDirectories,
    loadMappedDirectories
  });

  return (
    <Stack>
      <Title order={3}>Path Mapping Status</Title>
      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Text fw={600}>Path Mappings (Virtual vs Real)</Text>
            <Group gap="sm">
              <Text size="sm" c="dimmed">
                Showing {visibleDirectories.length} of {filteredDirectories.length}
                {activeStatusFilters.length > 0 ? " (status-filtered)" : ""}
                {" · "}
                Indexed {cacheEntriesTotal}
                {mappedTruncated ? " (list truncated)" : ""}
              </Text>
              {isSearchLoading && (
                <Group gap={6}>
                  <Loader size="xs" />
                  <Text size="xs" c="dimmed">Loading path mappings...</Text>
                </Group>
              )}
              {!isSearchLoading && isArrEnrichmentLoading && (
                <Group gap={6}>
                  <Loader size="xs" />
                  <Text size="xs" c="dimmed">Loading Arr state...</Text>
                </Group>
              )}
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
                disabled={reconcilingPath !== null}
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
          <Text size="xs" c="dimmed">
            Virtual Path is the Arr-facing shadow path. Real Path is the source target and does not
            need to match the virtual folder name.
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
              label="Library root and series shadow root filter"
              data={mappedRootOptions}
              value={mappedRootFilter}
              onChange={(value: string | null) => setMappedRootFilter(value ?? "all")}
            />
          </Group>

          <MultiSelect
            label="Status filter"
            placeholder="Select one or more statuses"
            data={MAPPER_STATUS_FILTER_OPTIONS}
            value={activeStatusFilters}
            onChange={setStatusFilters}
            clearable
            searchable
          />

          <Group gap="xs" wrap="wrap">
            <Text size="xs" c="dimmed">Status legend:</Text>
            <ThemeIcon size="sm" radius="xl" variant="light" color="green">
              <Text size="10px" fw={700}>A</Text>
            </ThemeIcon>
            <Text size="xs" c="dimmed">Arr ok</Text>
            <ThemeIcon size="sm" radius="xl" variant="light" color="orange">
              <Text size="10px" fw={700}>N</Text>
            </ThemeIcon>
            <Text size="xs" c="dimmed">Not in Arr</Text>
            <ThemeIcon size="sm" radius="xl" variant="light" color="red">
              <Text size="10px" fw={700}>M</Text>
            </ThemeIcon>
            <Text size="xs" c="dimmed">Missing target</Text>
          </Group>

          <Table withRowBorders={false} style={{ tableLayout: "fixed", width: "100%" }}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: "33%" }}>Virtual Path</Table.Th>
                <Table.Th style={{ width: "33%" }}>Real Path</Table.Th>
                <Table.Th style={{ width: "12%" }}>Last Result</Table.Th>
                <Table.Th style={{ width: "10%" }}>Updated</Table.Th>
                <Table.Th style={{ width: "12%" }}>Status</Table.Th>
              </Table.Tr>
            </Table.Thead>
          </Table>

          <Box style={{ width: "100%" }}>
            <Table withRowBorders={false} style={{ tableLayout: "fixed", width: "100%" }}>
              <Table.Tbody>
                {loadError ? (
                  <Table.Tr>
                    <Table.Td colSpan={5}>
                      <Text size="sm" c="red">
                        {loadError}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : filteredDirectories.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={5}>
                      <Text size="sm" c="dimmed">
                        {isSearchLoading
                          ? "Loading path mappings…"
                          : cacheBuilding && !cacheReady
                            ? "Building in-memory directory index… wait a few seconds."
                            : "No mapped directories match the current search/filter/status."}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  <MappedRows
                    directories={visibleDirectories}
                    cacheUpdatedAtMs={cacheUpdatedAtMs}
                    duplicatePrimaryPaths={duplicatePrimaryPaths}
                    excludedByDuplicate={excludedByDuplicate}
                    duplicatePathSet={duplicatePathSet}
                    excludedPathSet={excludedPathSet}
                    refreshingMovieId={refreshingMovieId}
                    reconcilingPath={reconcilingPath}
                    recentlyReconciledPath={recentlyReconciledPath}
                    deletingPath={deletingPath}
                    onCopy={copyToClipboard}
                    onOpen={openBrowsePath}
                    onRefreshRadarr={refreshMovieInRadarr}
                    onReconcilePath={reconcilePath}
                    onDeleteShadow={requestDelete}
                  />
                )}
              </Table.Tbody>
            </Table>
          </Box>

          {hasMoreRows && <Box ref={loadMoreRef} style={{ height: 1, width: "100%" }} />}

          <DirectoryPickerModal
            opened={browsePath !== null}
            title="Browse directory"
            roots={fsRoots}
            initialPath={browsePath ?? ""}
            onClose={() => setBrowsePath(null)}
            mode="browse"
          />

          <DeleteShadowConfirmModal
            opened={pendingDeletePath !== null}
            path={pendingDeletePath}
            onCancel={cancelDelete}
            onConfirm={confirmDelete}
          />
        </Stack>
      </Card>
    </Stack>
  );
}