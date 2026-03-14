import { Button, Card, Group, MultiSelect, Select, Stack, TextInput, Title } from "@mantine/core";

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
  return (
    <Stack>
      <Group justify="space-between" mt="xs">
        <Title order={5}>{title}</Title>
        <Button variant="light" onClick={onAdd}>
          Add Rule
        </Button>
      </Group>
      <Stack>
        {rows.map((row, index) => (
          <Card key={`${keyPrefix}-${index}`} withBorder>
            <Stack>
              {(() => {
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
              <Group grow align="flex-end">
                <MultiSelect
                  label="Match Tags"
                  placeholder={tagOptions.length > 0 ? "Select one or more tags" : "No tags available"}
                  data={tagOptions}
                  value={row.match}
                  searchable
                  clearable
                  nothingFoundMessage="No tags"
                  onChange={(values) => onMatchChange(index, values)}
                />
                <Select
                  label={idLabel}
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
                <TextInput
                  label="Name"
                  value={row.name}
                  onChange={(event) => onNameChange(index, event.currentTarget.value)}
                />
              </Group>
                );
              })()}
              <Group justify="flex-end">
                <Button color="red" variant="subtle" onClick={() => onRemove(index)}>
                  Remove Rule
                </Button>
              </Group>
            </Stack>
          </Card>
        ))}
      </Stack>
    </Stack>
  );
}
