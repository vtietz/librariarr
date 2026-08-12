import { Badge, Button, Card, Group, Table, Text, Title, Tooltip } from "@mantine/core";
import type { BucketDrift, PathDifference } from "../api/client";

/** Two ways Arr's view and the managed tree can differ. One is cosmetic and
 * needs no action (naming); the other is a pending reclassification the user
 * asked for in Arr and can apply here. */

export function PathDifferencesCard({ differences }: { differences: PathDifference[] }) {
  if (differences.length === 0) return null;
  return (
    <Card withBorder>
      <Title order={5}>Naming differences ({differences.length})</Title>
      <Text size="xs" c="dimmed" mt={4}>
        Radarr/Sonarr never rename their own copy when you reorganize your managed tree — this is
        expected, not a sync failure. Nothing is broken; the two names just point at the same file.
      </Text>
      <Table mt="sm" striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Title</Table.Th>
            <Table.Th>Arr shows</Table.Th>
            <Table.Th>You organized as</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {differences.map((diff, index) => (
            <Table.Tr key={index}>
              <Table.Td>
                {diff.title ?? "–"} <Badge size="xs" variant="light">{diff.kind}</Badge>
              </Table.Td>
              <Table.Td style={{ wordBreak: "break-all" }}>{diff.arr_path}</Table.Td>
              <Table.Td style={{ wordBreak: "break-all" }}>{diff.managed_path}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}

export function BucketDriftCard({
  drift,
  busy,
  onPreview,
  onApply
}: {
  drift: BucketDrift[];
  busy: boolean;
  onPreview: () => void;
  onApply: () => void;
}) {
  if (drift.length === 0) return null;
  return (
    <Card withBorder>
      <Group justify="space-between">
        <Title order={5}>Pending bucket moves ({drift.length})</Title>
        <Group gap="xs">
          <Tooltip label="Show exactly what would move, without changing anything.">
            <Button size="xs" variant="outline" onClick={onPreview} disabled={busy}>
              Preview
            </Button>
          </Tooltip>
          <Tooltip label="Move these managed folders into the bucket their Arr root folder now points at. Only these items are touched.">
            <Button size="xs" onClick={onApply} disabled={busy}>
              Apply
            </Button>
          </Tooltip>
        </Group>
      </Group>
      <Text size="xs" c="dimmed" mt={4}>
        You reassigned these items to another root folder in Radarr/Sonarr. Arr sends no webhook for
        that, so it is found by polling — and only the items listed here get reconciled.
      </Text>
      <Table mt="sm" striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Title</Table.Th>
            <Table.Th>Currently in</Table.Th>
            <Table.Th>Belongs in</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {drift.map((entry) => (
            <Table.Tr key={`${entry.kind}-${entry.id}`}>
              <Table.Td>
                {entry.title ?? "–"}{" "}
                <Badge size="xs" variant="light">
                  {entry.kind}
                </Badge>
              </Table.Td>
              <Table.Td style={{ wordBreak: "break-all" }}>{entry.current_bucket}</Table.Td>
              <Table.Td style={{ wordBreak: "break-all" }}>{entry.target_bucket}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Card>
  );
}

