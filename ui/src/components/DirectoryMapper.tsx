import {
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { getMappedDirectories, getMappedDirectoriesStreamUrl } from "../api/client";

type MappedDirectory = {
  shadow_root: string;
  virtual_path: string;
  real_path: string;
  target_exists: boolean;
};

export default function DirectoryMapper() {
  const [mappedDirectories, setMappedDirectories] = useState<MappedDirectory[]>([]);
  const [mappedSearch, setMappedSearch] = useState("");
  const [mappedRootFilter, setMappedRootFilter] = useState<string>("all");
  const [mappedRoots, setMappedRoots] = useState<string[]>([]);
  const [mappedTruncated, setMappedTruncated] = useState(false);
  const [isReloading, setIsReloading] = useState(false);

  const loadMappedDirectories = useCallback(async () => {
    setIsReloading(true);
    try {
      const result = await getMappedDirectories({
        limit: 5000
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
    } finally {
      setIsReloading(false);
    }
  }, []);

  useEffect(() => {
    void (async () => {
      await loadMappedDirectories();
    })();
  }, [loadMappedDirectories]);

  useEffect(() => {
    const source = new EventSource(getMappedDirectoriesStreamUrl({ intervalMs: 1000 }));

    source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { changed?: boolean };
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

  const filteredMappedDirectories = useMemo(() => {
    const loweredSearch = mappedSearch.trim().toLowerCase();
    return mappedDirectories.filter((mapped) => {
      if (mappedRootFilter !== "all" && mapped.shadow_root !== mappedRootFilter) {
        return false;
      }
      if (!loweredSearch) {
        return true;
      }
      return (
        mapped.virtual_path.toLowerCase().includes(loweredSearch) ||
        mapped.real_path.toLowerCase().includes(loweredSearch)
      );
    });
  }, [mappedDirectories, mappedRootFilter, mappedSearch]);

  const mappedRootOptions = useMemo(
    () => [
      { label: "All shadow roots", value: "all" },
      ...mappedRoots.map((root) => ({ label: root, value: root }))
    ],
    [mappedRoots]
  );

  return (
    <Stack>
      <Title order={3}>Directory Mapper</Title>

      <Card withBorder>
        <Stack>
          <Group justify="space-between">
            <Text fw={600}>Mapped Directories (Virtual vs Real)</Text>
            <Group gap="sm">
              <Text size="sm" c="dimmed">
                Showing {filteredMappedDirectories.length} of {mappedDirectories.length}
                {mappedTruncated ? " (list truncated)" : ""}
              </Text>
              <Button variant="light" size="xs" onClick={() => void loadMappedDirectories()} loading={isReloading}>
                Reload
              </Button>
            </Group>
          </Group>

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

          <Table striped withRowBorders={false}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Shadow Root</Table.Th>
                <Table.Th>Virtual Path</Table.Th>
                <Table.Th>Real Path</Table.Th>
                <Table.Th>Status</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {filteredMappedDirectories.map((mapped) => (
                <Table.Tr key={`${mapped.shadow_root}:${mapped.virtual_path}`}>
                  <Table.Td>{mapped.shadow_root}</Table.Td>
                  <Table.Td>{mapped.virtual_path}</Table.Td>
                  <Table.Td>{mapped.real_path}</Table.Td>
                  <Table.Td>
                    <Badge color={mapped.target_exists ? "green" : "red"}>
                      {mapped.target_exists ? "target exists" : "missing target"}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Stack>
      </Card>
    </Stack>
  );
}
