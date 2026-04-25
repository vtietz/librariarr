import { Badge, Card, Group, Progress, SimpleGrid, Stack, Text } from "@mantine/core";
import type { JobsSummary, RuntimeStatusResponse } from "../../api/client";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
  jobsSummary: JobsSummary | null;
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
  jobsSummary,
}: Props) {
  const healthStatus = runtimeStatus?.health?.status ?? "starting";
  const primaryHealthReason = runtimeStatus?.health?.reasons?.[0] ?? "Waiting for snapshot";

  const queuedJobs = jobsSummary?.queued ?? 0;
  const runningJobs = jobsSummary?.running ?? 0;
  const failedJobs = jobsSummary?.failed ?? 0;
  const activeJobs = jobsSummary?.active ?? 0;

  const queueTotal = queuedJobs + runningJobs + failedJobs;
  const queueScale = queueTotal > 0 ? queueTotal : 1;
  const queuedPct = (queuedJobs / queueScale) * 100;
  const runningPct = (runningJobs / queueScale) * 100;
  const failedPct = (failedJobs / queueScale) * 100;

  return (
    <>
      <Text fw={600} size="sm" c="dimmed">System Status</Text>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Card withBorder h={126}>
          <Group justify="space-between">
            <Text fw={600}>Config Draft</Text>
            <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
              {hasUnsavedChanges ? "unsaved changes" : "in sync"}
            </Badge>
          </Group>
          <Text c="dimmed" size="sm" mt="xs">
            UI draft and saved file consistency
          </Text>
        </Card>

        <Card withBorder h={126}>
          <Group justify="space-between">
            <Text fw={600}>System Health</Text>
            <Badge color={healthBadgeColor(healthStatus)}>{healthStatus}</Badge>
          </Group>
          <Text c="dimmed" size="sm" mt="xs" lineClamp={2}>
            {primaryHealthReason}
          </Text>
          <Text c="dimmed" size="xs" mt={4}>
            health = runtime + cache freshness + job failures
          </Text>
        </Card>

        <Card withBorder h={126}>
          <Group justify="space-between" mb={6}>
            <Text fw={600}>Queue Health</Text>
            <Badge color={activeJobs > 0 ? "blue" : "gray"}>{activeJobs} active</Badge>
          </Group>
          <Stack gap={6}>
            <Group gap={6}>
              <Badge variant="light" color="gray">queued {queuedJobs}</Badge>
              <Badge variant="light" color="blue">running {runningJobs}</Badge>
              <Badge variant="light" color="red">failed {failedJobs}</Badge>
            </Group>
            <Progress size="xs" radius="xl" value={queuedPct} color="gray" />
            <Progress size="xs" radius="xl" value={runningPct} color="blue" />
            <Progress size="xs" radius="xl" value={failedPct} color="red" />
          </Stack>
        </Card>
      </SimpleGrid>
    </>
  );
}
