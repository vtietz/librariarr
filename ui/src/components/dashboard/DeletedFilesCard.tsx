import {
  ActionIcon,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Select,
  Stack,
  Table,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconTrash, IconRestore } from "@tabler/icons-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  clearDeletedFiles,
  deleteDeletedFile,
  getDeletedFiles,
  restoreDeletedFile,
  type DeletedFilesResponse,
} from "../../api/client";

type DeletedFileEntry = DeletedFilesResponse["items"][number];

function formatAgeSeconds(updatedAt: number): string {
  const delta = Math.max(0, Math.floor(Date.now() / 1000 - updatedAt));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
}

export default function DeletedFilesCard() {
  const [data, setData] = useState<DeletedFilesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [managedRootFilter, setManagedRootFilter] = useState<string>("all");
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const loadDeleted = useCallback(async () => {
    try {
      const result = await getDeletedFiles({
        managedRoot: managedRootFilter === "all" ? undefined : managedRootFilter,
        limit: 1000,
      });
      setData(result);
      setError(null);
    } catch (err) {
      console.error("[DeletedFiles] failed to load deleted files", err);
      setError("Unable to load deleted files.");
    } finally {
      setLoading(false);
    }
  }, [managedRootFilter]);

  useEffect(() => {
    let active = true;
    let inFlight = false;

    const poll = async () => {
      if (!active || inFlight) {
        return;
      }
      inFlight = true;
      try {
        await loadDeleted();
      } finally {
        inFlight = false;
      }
    };

    void poll();
    const interval = window.setInterval(() => {
      void poll();
    }, 7000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [loadDeleted]);

  const rows = data?.items ?? [];
  const canClearAll = rows.length > 0 && !clearing;

  const rootOptions = useMemo(() => {
    const roots = data?.managed_roots ?? [];
    const options = [{ value: "all", label: "All managed roots" }];
    for (const root of roots) {
      options.push({ value: root, label: root });
    }
    return options;
  }, [data?.managed_roots]);

  const handleRestore = async (item: DeletedFileEntry) => {
    setBusyPath(item.path);
    try {
      await restoreDeletedFile(item.path);
      await loadDeleted();
    } catch (err) {
      console.error("[DeletedFiles] restore failed", err);
      setError("Restore failed. Target may already exist.");
    } finally {
      setBusyPath(null);
    }
  };

  const handleDelete = async (item: DeletedFileEntry) => {
    setBusyPath(item.path);
    try {
      await deleteDeletedFile(item.path);
      await loadDeleted();
    } catch (err) {
      console.error("[DeletedFiles] delete failed", err);
      setError("Delete failed.");
    } finally {
      setBusyPath(null);
    }
  };

  const handleClearAll = async () => {
    setClearing(true);
    try {
      await clearDeletedFiles(managedRootFilter === "all" ? undefined : managedRootFilter);
      await loadDeleted();
    } catch (err) {
      console.error("[DeletedFiles] clear-all failed", err);
      setError("Clear all failed.");
    } finally {
      setClearing(false);
    }
  };

  return (
    <Card withBorder>
      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Group gap="xs">
            <Text fw={600}>Deleted Files</Text>
            <Badge color={rows.length > 0 ? "yellow" : "green"}>
              {rows.length > 0 ? `${rows.length} pending` : "empty"}
            </Badge>
          </Group>
          <Group gap="xs">
            <Select
              size="xs"
              w={260}
              data={rootOptions}
              value={managedRootFilter}
              onChange={(value) => setManagedRootFilter(value ?? "all")}
            />
            <Button size="xs" color="red" variant="light" onClick={() => void handleClearAll()} disabled={!canClearAll} loading={clearing}>
              Clear all
            </Button>
          </Group>
        </Group>

        {loading && (
          <Group gap="xs">
            <Loader size="xs" />
            <Text size="sm" c="dimmed">Loading deleted files…</Text>
          </Group>
        )}

        {!loading && error && (
          <Text size="sm" c="red">{error}</Text>
        )}

        {!loading && !error && rows.length === 0 && (
          <Text size="sm" c="dimmed">No deleted files waiting in .deletedByLibrariarr.</Text>
        )}

        {!loading && !error && rows.length > 0 && (
          <Table striped withTableBorder highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Deleted file</Table.Th>
                <Table.Th>Restore target</Table.Th>
                <Table.Th>Size</Table.Th>
                <Table.Th>Age</Table.Th>
                <Table.Th>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((item) => (
                <Table.Tr key={item.path}>
                  <Table.Td>
                    <Text size="xs" ff="monospace">{item.path}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" ff="monospace" c={item.exists ? "yellow" : undefined}>
                      {item.restore_path}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{formatBytes(item.size_bytes)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs">{formatAgeSeconds(item.updated_at)}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      <Tooltip label={item.exists ? "Target exists, restore blocked" : "Restore this file"} withArrow>
                        <ActionIcon
                          size="sm"
                          color="blue"
                          variant="light"
                          disabled={item.exists || busyPath === item.path || clearing}
                          loading={busyPath === item.path}
                          onClick={() => void handleRestore(item)}
                          aria-label="Restore deleted file"
                        >
                          <IconRestore size={14} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip label="Delete permanently" withArrow>
                        <ActionIcon
                          size="sm"
                          color="red"
                          variant="light"
                          disabled={busyPath === item.path || clearing}
                          loading={busyPath === item.path}
                          onClick={() => void handleDelete(item)}
                          aria-label="Delete deleted file permanently"
                        >
                          <IconTrash size={14} />
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Card>
  );
}
