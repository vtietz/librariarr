import { Badge, Card, Group, ScrollArea, Table, Text } from "@mantine/core";
import { badgeForTask } from "../dashboardFormatters";

export type DashboardTaskStatus = "idle" | "queued" | "running" | "error";

export type TaskSlot = {
  id: string;
  name: string;
  source: string;
  status: DashboardTaskStatus;
  detail: string;
  queuedAt: string;
  duration: string;
};

type Props = {
  taskSlots: TaskSlot[];
  uncategorizedTaskCount: number;
};

const taskColumnStyles = {
  task: { width: "18rem" },
  status: { width: "7.5rem" },
  source: { width: "9rem" },
  queued: { width: "8rem" },
  duration: { width: "7rem" },
} as const;

export default function TaskSlotsCard({ taskSlots, uncategorizedTaskCount }: Props) {
  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Task Details</Text>
        <Text size="xs" c="dimmed">
          {uncategorizedTaskCount > 0
            ? `${uncategorizedTaskCount} additional queued/running task(s) shown below`
            : "all active tasks mapped to slots"}
        </Text>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        Auto-refreshes every 3s. Runtime reconcile is single-worker; cache rebuild tasks may run in parallel.
      </Text>
      <ScrollArea type="auto" scrollbars="x">
        <Table
          highlightOnHover
          withTableBorder
          withColumnBorders
          style={{ tableLayout: "fixed", minWidth: "58rem" }}
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={taskColumnStyles.task}>Task</Table.Th>
              <Table.Th style={taskColumnStyles.status}>Status</Table.Th>
              <Table.Th style={taskColumnStyles.source}>Source</Table.Th>
              <Table.Th>Detail</Table.Th>
              <Table.Th style={taskColumnStyles.queued}>Queued</Table.Th>
              <Table.Th style={taskColumnStyles.duration}>Duration</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {taskSlots.map((slot) => (
              <Table.Tr key={slot.id}>
                <Table.Td style={taskColumnStyles.task}>{slot.name}</Table.Td>
                <Table.Td style={taskColumnStyles.status}>
                  <Badge color={badgeForTask(slot.status)} style={{ width: "6.5rem", justifyContent: "center" }}>
                    {slot.status}
                  </Badge>
                </Table.Td>
                <Table.Td style={taskColumnStyles.source}>
                  <Text size="sm" c="dimmed">{slot.source}</Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" c="dimmed">{slot.detail}</Text>
                </Table.Td>
                <Table.Td style={taskColumnStyles.queued}>
                  <Text size="sm" c="dimmed">{slot.queuedAt}</Text>
                </Table.Td>
                <Table.Td style={taskColumnStyles.duration}>
                  <Text size="sm" c="dimmed">{slot.duration}</Text>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </Card>
  );
}
