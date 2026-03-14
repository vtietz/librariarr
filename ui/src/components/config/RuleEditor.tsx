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
  TextInput,
  Title
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useMemo } from "react";

type RuleRow = {
  match: string[];
  name: string;
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
  onNameChange: (index: number, name: string) => void;
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
  onIdChange,
  onNameChange
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
        <Button variant="light" onClick={onAdd}>
          Add Rule
        </Button>
      </Group>
      <Card withBorder p="sm">
        <Table verticalSpacing="xs" horizontalSpacing="sm" layout="fixed">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Match Tags</Table.Th>
              <Table.Th>{idLabel}</Table.Th>
              <Table.Th>Name</Table.Th>
              <Table.Th w={44} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={4}>
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
                const currentOptionLabel =
                  mappedIdOptions.find((item) => item.value === currentIdValue)?.label ?? currentIdValue;
                const idName = currentOptionLabel.startsWith(`${currentIdValue} - `)
                  ? currentOptionLabel.slice(currentIdValue.length + 3)
                  : currentOptionLabel;

                return (
                  <Table.Tr key={`${keyPrefix}-${index}`}>
                    <Table.Td>
                      <MultiSelect
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
                      <Group gap="xs" wrap="nowrap" align="center">
                        <Select
                          aria-label={idLabel}
                          data={mappedIdOptions}
                          value={currentIdValue}
                          searchable
                          nothingFoundMessage="No values"
                          style={{ flex: 1 }}
                          onChange={(value) => {
                            const parsed = Number(value);
                            if (!Number.isNaN(parsed) && Number.isFinite(parsed)) {
                              onIdChange(index, parsed);
                            }
                          }}
                        />
                        <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                          {idName}
                        </Text>
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      <TextInput
                        aria-label="Name"
                        value={row.name}
                        onChange={(event) => onNameChange(index, event.currentTarget.value)}
                      />
                    </Table.Td>
                    <Table.Td>
                      <ActionIcon
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
