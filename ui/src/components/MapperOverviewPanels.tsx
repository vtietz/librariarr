import { Button, Card, Group, Select, SimpleGrid, Stack, Table, Text } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import {
  getFsRoots,
  getRadarrProfiles,
  getRadarrRootFolders,
  getSonarrProfiles,
  getSonarrRootFolders,
  listFs
} from "../api/client";
import type { ConfigModel } from "../types/config";

type ExplorerEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  is_symlink: boolean;
};

type Props = {
  draft: ConfigModel;
};

export default function MapperOverviewPanels({ draft }: Props) {
  const [roots, setRoots] = useState<string[]>([]);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [entries, setEntries] = useState<ExplorerEntry[]>([]);
  const [radarrRoots, setRadarrRoots] = useState<Array<{ path: string }>>([]);
  const [sonarrRoots, setSonarrRoots] = useState<Array<{ path: string }>>([]);
  const [radarrProfiles, setRadarrProfiles] = useState<Array<{ id: number; name: string }>>([]);
  const [sonarrProfiles, setSonarrProfiles] = useState<Array<{ id: number; name: string }>>([]);

  useEffect(() => {
    void (async () => {
      const [
        foundRoots,
        foundRadarrRoots,
        foundSonarrRoots,
        foundRadarrProfiles,
        foundSonarrProfiles
      ] = await Promise.all([
        getFsRoots(),
        getRadarrRootFolders(),
        getSonarrRootFolders(),
        getRadarrProfiles(),
        getSonarrProfiles()
      ]);
      setRoots(foundRoots);
      setSelectedPath(foundRoots[0] ?? null);
      setRadarrRoots(foundRadarrRoots);
      setSonarrRoots(foundSonarrRoots);
      setRadarrProfiles(foundRadarrProfiles);
      setSonarrProfiles(foundSonarrProfiles);
    })();
  }, []);

  useEffect(() => {
    if (!selectedPath) {
      return;
    }
    void (async () => {
      const nextEntries = await listFs(selectedPath);
      setEntries(nextEntries);
    })();
  }, [selectedPath]);

  const rootOptions = useMemo(
    () => roots.map((root) => ({ label: root, value: root })),
    [roots]
  );

  return (
    <SimpleGrid cols={{ base: 1, lg: 2 }}>
      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Text fw={600}>Container Filesystem</Text>
          <Select
            w={360}
            data={rootOptions}
            placeholder="Select allowed root"
            value={selectedPath}
            onChange={setSelectedPath}
          />
        </Group>

        <Table striped withRowBorders={false}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Action</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {entries.map((entry) => (
              <Table.Tr key={entry.path}>
                <Table.Td>{entry.name}</Table.Td>
                <Table.Td>{entry.is_dir ? "Directory" : "File"}</Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="light"
                    disabled={!entry.is_dir}
                    onClick={() => setSelectedPath(entry.path)}
                  >
                    Open
                  </Button>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>

      <Card withBorder>
        <Stack>
          <Text fw={600}>Current Root Mappings</Text>
          {draft.paths.root_mappings.map((mapping, index) => (
            <Text key={`mapping-${index}`} size="sm">
              {mapping.nested_root} → {mapping.shadow_root}
            </Text>
          ))}
          <Text fw={600} mt="md">
            Radarr Root Folders
          </Text>
          {radarrRoots.map((folder, index) => (
            <Text key={`radarr-root-${index}`} size="sm">
              {folder.path}
            </Text>
          ))}
          <Text fw={600} mt="md">
            Sonarr Root Folders
          </Text>
          {sonarrRoots.map((folder, index) => (
            <Text key={`sonarr-root-${index}`} size="sm">
              {folder.path}
            </Text>
          ))}
          <Text fw={600} mt="md">
            Radarr Profiles
          </Text>
          {radarrProfiles.map((profile) => (
            <Text key={`radarr-profile-${profile.id}`} size="sm">
              {profile.id}: {profile.name}
            </Text>
          ))}
          <Text fw={600} mt="md">
            Sonarr Profiles
          </Text>
          {sonarrProfiles.map((profile) => (
            <Text key={`sonarr-profile-${profile.id}`} size="sm">
              {profile.id}: {profile.name}
            </Text>
          ))}
        </Stack>
      </Card>
    </SimpleGrid>
  );
}
