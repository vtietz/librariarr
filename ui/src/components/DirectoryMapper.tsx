import {
  Badge,
  Card,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import { getMappedDirectories } from "../api/client";

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

  const loadMappedDirectories = async (search: string, rootFilter: string) => {
    const result = await getMappedDirectories({
      search: search || undefined,
      shadowRoot: rootFilter === "all" ? undefined : rootFilter,
      limit: 1000
    });
    setMappedDirectories(result.items);
    setMappedRoots(result.shadow_roots);
    setMappedTruncated(result.truncated);
  };

  useEffect(() => {
    void (async () => {
      await loadMappedDirectories("", "all");
    })();
  }, []);

  useEffect(() => {
    void loadMappedDirectories(mappedSearch, mappedRootFilter);
  }, [mappedSearch, mappedRootFilter]);

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
            <Badge color="blue">{mappedDirectories.length}</Badge>
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
              {mappedDirectories.map((mapped) => (
                <Table.Tr key={mapped.virtual_path}>
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

          {mappedTruncated ? (
            <Text size="sm" c="dimmed">
              Results truncated to 1000 entries. Narrow with search or shadow root filter.
            </Text>
          ) : null}
        </Stack>
      </Card>
    </Stack>
  );
}
