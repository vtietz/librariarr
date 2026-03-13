import {
  Button,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput
} from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import { listFs } from "../api/client";

type DirectoryEntry = {
  name: string;
  path: string;
  is_dir: boolean;
  is_symlink: boolean;
};

type ApiErrorShape = {
  response?: {
    status?: number;
    data?: {
      detail?: unknown;
    };
  };
  message?: unknown;
};

const parseDirectoryPickerError = (loadError: unknown): string => {
  if (typeof loadError === "object" && loadError !== null) {
    const apiError = loadError as ApiErrorShape;
    const status = apiError.response?.status;
    const detail = apiError.response?.data?.detail;

    if (status === 404) {
      return "Directory does not exist in the container yet. Create it first or choose a different path.";
    }
    if (status === 403) {
      return "Path is outside allowed roots. Choose one of the configured root paths.";
    }
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (typeof apiError.message === "string" && apiError.message.trim()) {
      return apiError.message;
    }
  }

  return "Failed to list directory";
};

type Props = {
  opened: boolean;
  title: string;
  roots: string[];
  initialPath: string;
  onClose: () => void;
  onSelect: (path: string) => void;
};

export default function DirectoryPickerModal({
  opened,
  title,
  roots,
  initialPath,
  onClose,
  onSelect
}: Props) {
  const [currentPath, setCurrentPath] = useState<string>("");
  const [entries, setEntries] = useState<DirectoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!opened) {
      return;
    }

    const fallbackPath = roots[0] ?? "";
    setCurrentPath(initialPath || fallbackPath);
  }, [opened, initialPath, roots]);

  useEffect(() => {
    if (!opened || !currentPath) {
      return;
    }

    let cancelled = false;
    const load = async () => {
      setIsLoading(true);
      setError(null);
      try {
        const nextEntries = await listFs(currentPath);
        if (!cancelled) {
          setEntries(nextEntries);
        }
      } catch (loadError: unknown) {
        if (!cancelled) {
          setError(parseDirectoryPickerError(loadError));
          setEntries([]);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [opened, currentPath]);

  const rootOptions = useMemo(
    () => roots.map((root) => ({ label: root, value: root })),
    [roots]
  );

  const selectedRoot = useMemo(() => {
    const matches = roots.filter((root) => currentPath === root || currentPath.startsWith(`${root}/`));
    if (matches.length === 0) {
      return null;
    }
    return matches.sort((left, right) => right.length - left.length)[0];
  }, [roots, currentPath]);

  const handleUp = () => {
    const lastSlash = currentPath.lastIndexOf("/");
    if (lastSlash <= 0) {
      return;
    }
    setCurrentPath(currentPath.slice(0, lastSlash));
  };

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="lg" centered>
      <Stack>
        <Select
          data={rootOptions}
          label="Allowed root"
          value={selectedRoot}
          onChange={(value) => setCurrentPath(value ?? "")}
          searchable
        />

        <TextInput label="Current path" value={currentPath} readOnly />

        <Group>
          <Button variant="light" onClick={handleUp} disabled={!currentPath}>
            Up
          </Button>
          <Button onClick={() => onSelect(currentPath)} disabled={!currentPath}>
            Select current path
          </Button>
        </Group>

        {isLoading ? <Loader size="sm" /> : null}
        {error ? (
          <Text size="sm" c="red">
            {error}
          </Text>
        ) : null}

        <Table striped withRowBorders={false}>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {entries
              .filter((entry) => entry.is_dir)
              .map((entry) => (
                <Table.Tr key={entry.path}>
                  <Table.Td>{entry.name}</Table.Td>
                  <Table.Td>{entry.is_symlink ? "Directory (symlink)" : "Directory"}</Table.Td>
                  <Table.Td>
                    <Group gap="xs">
                      <Button size="xs" variant="light" onClick={() => setCurrentPath(entry.path)}>
                        Open
                      </Button>
                      <Button size="xs" onClick={() => onSelect(entry.path)}>
                        Select
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
          </Table.Tbody>
        </Table>
      </Stack>
    </Modal>
  );
}
