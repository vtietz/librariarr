import { Button, Card, Group, NumberInput, Stack, TextInput, Title } from "@mantine/core";
import { parseCommaSeparated } from "./ruleParsers";

type RuleRow = {
  match: string[];
  name: string;
};

type Props<T extends RuleRow> = {
  title: string;
  idLabel: string;
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
              <Group grow align="flex-end">
                <TextInput
                  label="Match Tokens (comma-separated)"
                  value={row.match.join(", ")}
                  onChange={(event) => onMatchChange(index, parseCommaSeparated(event.currentTarget.value))}
                />
                <NumberInput
                  label={idLabel}
                  value={readId(row)}
                  min={1}
                  allowDecimal={false}
                  onChange={(value) => onIdChange(index, Number(value) || 1)}
                />
                <TextInput
                  label="Name"
                  value={row.name}
                  onChange={(event) => onNameChange(index, event.currentTarget.value)}
                />
              </Group>
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
