import {
  ActionIcon,
  Button,
  Card,
  Group,
  MultiSelect,
  Select,
  Stack,
  Table,
  Text,
  Title
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useMemo } from "react";
import HelpLabel from "./HelpLabel";

type RuleRow = {
  match: string[];
};

type Props<T extends RuleRow> = {
  title: string;
  idLabel: string;
  tagOptions: string[];
  idOptions: Array<{ value: string; label: string }>;
  rows: T[];
  keyPrefix: string;
  readId: (row: T) => number;
  onAdd: () => void;
  onRemove: (index: number) => void;
  onMatchChange: (index: number, match: string[]) => void;
  onIdChange: (index: number, id: number) => void;
};

export default function RuleEditor<T extends RuleRow>({
  title,
  idLabel,
  tagOptions,
  idOptions,
  rows,
  keyPrefix,
  readId,
  onAdd,
  onRemove,
  onMatchChange,
  onIdChange
}: Props<T>) {
  const mergedTagOptions = useMemo(() => {
    const normalizedRows = rows
      .flatMap((row) => row.match)
      .map((tag) => String(tag).trim().toLowerCase())
      .filter((tag) => tag.length > 0);
    return Array.from(new Set([...tagOptions, ...normalizedRows])).sort((left, right) =>
      left.localeCompare(right)
    );
  }, [rows, tagOptions]);

  return (
    <Stack gap="xs">
      <Group justify="space-between" mt="xs">
        <Title order={5}>{title}</Title>
        <Button variant="light" size="xs" onClick={onAdd}>
          Add Rule
        </Button>
      </Group>
      <Card withBorder p="xs">
        <Table verticalSpacing={6} horizontalSpacing="xs" layout="fixed">
          <Table.Thead>
            <Table.Tr>
              <Table.Th py={6} fz="sm">
                <HelpLabel
                  label="Match Tags"
                  help="All listed tags must match for this mapping rule to apply."
                />
              </Table.Th>
              <Table.Th py={6} fz="sm">
                <HelpLabel
                  label={idLabel}
                  help="Target ID assigned when the match tags rule is satisfied."
                />
              </Table.Th>
              <Table.Th py={6} w={44} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text c="dimmed" size="sm">
                    No rules yet. Use Add Rule to create one.
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              rows.map((row, index) => {
                const currentId = readId(row);
                const currentIdValue = String(currentId);
                const hasCurrentIdOption = idOptions.some((item) => item.value === currentIdValue);
                const mappedIdOptions = hasCurrentIdOption
                  ? idOptions
                  : [
                      ...idOptions,
                      {
                        value: currentIdValue,
                        label: `${currentId} (configured, unavailable)`
                      }
                    ];

                return (
                  <Table.Tr key={`${keyPrefix}-${index}`}>
                    <Table.Td>
                      <MultiSelect
                        size="sm"
                        aria-label="Match Tags"
                        placeholder={mergedTagOptions.length > 0 ? "Select tags" : "No tags available"}
                        data={mergedTagOptions}
                        value={row.match}
                        searchable
                        clearable
                        nothingFoundMessage="No tags"
                        onChange={(values) => onMatchChange(index, values)}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Select
                        size="sm"
                        aria-label={idLabel}
                        data={mappedIdOptions}
                        value={currentIdValue}
                        searchable
                        nothingFoundMessage="No values"
                        onChange={(value) => {
                          const parsed = Number(value);
                          if (!Number.isNaN(parsed) && Number.isFinite(parsed)) {
                            onIdChange(index, parsed);
                          }
                        }}
                      />
                    </Table.Td>
                    <Table.Td>
                      <ActionIcon
                        size="sm"
                        color="red"
                        variant="subtle"
                        aria-label="Remove rule"
                        onClick={() => onRemove(index)}
                      >
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Table.Td>
                  </Table.Tr>
                );
              })
            )}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
