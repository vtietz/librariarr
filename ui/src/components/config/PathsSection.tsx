import {
  ActionIcon,
  Button,
  Card,
  Group,
  Table,
  TagsInput,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { IconFolder, IconTrash } from "@tabler/icons-react";
import type { RootMapping } from "../../types/config";
import { EXCLUDE_PATH_SUGGESTIONS, normalizeExcludePaths } from "./pathExcludes";
import HelpLabel from "./HelpLabel";

type Props = {
  rootMappings: RootMapping[];
  excludePaths: string[];
  onAddMapping: () => void;
  onRemoveMapping: (index: number) => void;
  onSetMapping: (index: number, key: "nested_root" | "shadow_root", value: string) => void;
  onOpenPicker: (index: number, key: "nested_root" | "shadow_root") => void;
  onExcludePathsChange: (next: string[]) => void;
};

export default function PathsSection({
  rootMappings,
  excludePaths,
  onAddMapping,
  onRemoveMapping,
  onSetMapping,
  onOpenPicker,
  onExcludePathsChange
}: Props) {
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Title order={4}>Root Mappings</Title>
        <Button variant="light" onClick={onAddMapping}>
          Add Mapping
        </Button>
      </Group>
      <Table mt="sm" verticalSpacing={6} horizontalSpacing="xs" layout="fixed">
        <Table.Thead>
          <Table.Tr>
            <Table.Th py={6} fz="sm">
              <HelpLabel
                label="Nested Root"
                help="Source folder to scan for real media folders."
              />
            </Table.Th>
            <Table.Th py={6} w={44} />
            <Table.Th py={6} fz="sm">
              <HelpLabel
                label="Shadow Root"
                help="Arr-managed root where links or imports are mirrored."
              />
            </Table.Th>
            <Table.Th py={6} w={44} />
            <Table.Th py={6} w={44} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rootMappings.length === 0 ? (
            <Table.Tr>
              <Table.Td colSpan={5}>
                <Text c="dimmed" size="sm">No mappings yet. Use Add Mapping.</Text>
              </Table.Td>
            </Table.Tr>
          ) : (
            rootMappings.map((mapping, index) => (
              <Table.Tr key={`mapping-${index}`}>
                <Table.Td>
                  <TextInput
                    size="sm"
                    aria-label={`Nested Root ${index + 1}`}
                    value={mapping.nested_root}
                    onChange={(event) => onSetMapping(index, "nested_root", event.currentTarget.value)}
                  />
                </Table.Td>
                <Table.Td>
                  <ActionIcon
                    size="sm"
                    variant="light"
                    aria-label="Pick nested root directory"
                    onClick={() => onOpenPicker(index, "nested_root")}
                  >
                    <IconFolder size={16} />
                  </ActionIcon>
                </Table.Td>
                <Table.Td>
                  <TextInput
                    size="sm"
                    aria-label={`Shadow Root ${index + 1}`}
                    value={mapping.shadow_root}
                    onChange={(event) => onSetMapping(index, "shadow_root", event.currentTarget.value)}
                  />
                </Table.Td>
                <Table.Td>
                  <ActionIcon
                    size="sm"
                    variant="light"
                    aria-label="Pick shadow root directory"
                    onClick={() => onOpenPicker(index, "shadow_root")}
                  >
                    <IconFolder size={16} />
                  </ActionIcon>
                </Table.Td>
                <Table.Td>
                  <ActionIcon
                    size="sm"
                    color="red"
                    variant="subtle"
                    aria-label="Remove mapping"
                    onClick={() => onRemoveMapping(index)}
                  >
                    <IconTrash size={16} />
                  </ActionIcon>
                </Table.Td>
              </Table.Tr>
            ))
          )}
        </Table.Tbody>
      </Table>
      <TagsInput
        mt="md"
        label={
          <HelpLabel
            label="Exclude Paths"
            help="Case-insensitive glob patterns, relative to each nested root, that should be skipped during discovery. Supports directories (trailing /) and file patterns."
          />
        }
        description="Case-insensitive glob-style patterns, relative to each nested root (e.g. .deletedByTMM/, .actors/, specials/, trailers/, *-trailer.*, .librariarr/**)"
        placeholder="Add pattern and press Enter"
        data={EXCLUDE_PATH_SUGGESTIONS}
        value={excludePaths}
        splitChars={[","]}
        clearable
        acceptValueOnBlur
        onChange={(values) => onExcludePathsChange(normalizeExcludePaths(values))}
      />
    </Card>
  );
}