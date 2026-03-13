import { Badge, Card, Group, SimpleGrid, Stack, Text, Title } from "@mantine/core";

type Status = "idle" | "ok" | "warning" | "disabled";

type Props = {
  radarrStatus: Status;
  sonarrStatus: Status;
  hasUnsavedChanges: boolean;
  lastDryRunSummary: string;
};

const toneByStatus: Record<Status, string> = {
  idle: "gray",
  ok: "green",
  warning: "yellow",
  disabled: "blue"
};

export default function Dashboard({
  radarrStatus,
  sonarrStatus,
  hasUnsavedChanges,
  lastDryRunSummary
}: Props) {
  return (
    <Stack>
      <Title order={3}>Dashboard</Title>
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Radarr Diagnostics</Text>
            <Badge color={toneByStatus[radarrStatus]}>{radarrStatus}</Badge>
          </Group>
        </Card>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Sonarr Diagnostics</Text>
            <Badge color={toneByStatus[sonarrStatus]}>{sonarrStatus}</Badge>
          </Group>
        </Card>
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={600}>Config Draft</Text>
            <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
              {hasUnsavedChanges ? "unsaved changes" : "in sync"}
            </Badge>
          </Group>
        </Card>
      </SimpleGrid>
      <Card withBorder>
        <Text fw={600}>Last Dry-Run</Text>
        <Text c="dimmed" size="sm">
          {lastDryRunSummary || "No dry-run executed yet."}
        </Text>
      </Card>
    </Stack>
  );
}
