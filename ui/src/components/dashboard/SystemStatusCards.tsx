import { Badge, Card, Group, SimpleGrid, Text } from "@mantine/core";
import type { RuntimeStatusResponse } from "../../api/client";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
  jobsSummary: unknown;
};

function healthBadgeColor(healthStatus: string): string {
  if (healthStatus === "ok") {
    return "green";
  }
  if (healthStatus === "degraded") {
    return "yellow";
  }
  return "gray";
}

export default function SystemStatusCards({
  hasUnsavedChanges,
  runtimeStatus,
}: Props) {
  const healthStatus = runtimeStatus?.health?.status ?? "starting";
  const primaryHealthReason = runtimeStatus?.health?.reasons?.[0] ?? "Waiting for snapshot";

  return (
    <SimpleGrid cols={{ base: 1, md: 2 }}>
      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>System Health</Text>
          <Badge color={healthBadgeColor(healthStatus)}>{healthStatus}</Badge>
        </Group>
        <Text c="dimmed" size="sm" mt="xs" lineClamp={2}>
          {primaryHealthReason}
        </Text>
      </Card>

      <Card withBorder>
        <Group justify="space-between">
          <Text fw={600}>Config</Text>
          <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
            {hasUnsavedChanges ? "unsaved changes" : "in sync"}
          </Badge>
        </Group>
        <Text c="dimmed" size="sm" mt="xs">
          UI draft and saved file consistency
        </Text>
      </Card>
    </SimpleGrid>
  );
}
