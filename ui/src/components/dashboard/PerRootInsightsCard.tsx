import { Badge, Card, Group, Progress, Stack, Text } from "@mantine/core";
import type { RuntimeStatusResponse } from "../../api/client";
import { formatAge } from "../dashboardFormatters";

type RootStat = NonNullable<RuntimeStatusResponse["library_root_stats"]>[number];

type Props = {
  runtimeStatus: RuntimeStatusResponse | null;
};

function rootDisplayName(path: string): string {
  return path.replace(/\/+$/, "") || path;
}

function arrTypeLabel(arrType: string): string {
  if (arrType === "radarr") return "movies";
  if (arrType === "sonarr") return "series";
  return arrType;
}

function RootRow({ root }: { root: RootStat }) {
  const total = root.planned || 1;
  const matchedPct = (root.matched / total) * 100;
  const skippedPct = (root.skipped / total) * 100;
  const totalFiles = root.projected_files + root.unchanged_files + root.skipped_files;

  return (
    <Stack gap={4}>
      <Group justify="space-between">
        <Group gap="xs">
          <Text size="sm" fw={500}>
            {rootDisplayName(root.library_root)}
          </Text>
          <Badge size="xs" variant="light" color="gray">
            {arrTypeLabel(root.arr_type)}
          </Badge>
        </Group>
        <Group gap="xs">
          <Text size="xs" c="dimmed">
            {root.planned} items
          </Text>
          {totalFiles > 0 && (
            <Text size="xs" c="dimmed">
              · {totalFiles} files
            </Text>
          )}
          {root.updated_at > 0 && (
            <Text size="xs" c="dimmed">
              · {formatAge(root.updated_at)}
            </Text>
          )}
        </Group>
      </Group>
      <Progress.Root size="lg">
        <Progress.Section value={matchedPct} color="teal" />
        {skippedPct > 0 && (
          <Progress.Section value={skippedPct} color="yellow" />
        )}
      </Progress.Root>
      <Group gap="md">
        <Text size="xs" c="dimmed">
          <Text span c="teal" fw={600}>●</Text> {root.matched} matched
        </Text>
        {root.skipped > 0 && (
          <Text size="xs" c="dimmed">
            <Text span c="yellow" fw={600}>●</Text> {root.skipped} unmatched
          </Text>
        )}
        {root.projected_files > 0 && (
          <Text size="xs" c="dimmed">
            {root.projected_files} projected
          </Text>
        )}
        {root.unchanged_files > 0 && (
          <Text size="xs" c="dimmed">
            {root.unchanged_files} unchanged
          </Text>
        )}
      </Group>
    </Stack>
  );
}

export default function PerRootInsightsCard({ runtimeStatus }: Props) {
  const roots = runtimeStatus?.library_root_stats ?? [];
  const isReconciling = runtimeStatus?.current_task?.state === "running";

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Library Roots</Text>
        <Badge color="blue" size="sm">
          {roots.length} roots
        </Badge>
      </Group>
      {roots.length === 0 && (
        <Text size="sm" c="dimmed">
          {isReconciling ? "Syncing — root stats appear after first reconcile…" : "Waiting for first reconcile…"}
        </Text>
      )}
      <Stack gap="md">
        {roots.map((root) => (
          <RootRow key={root.library_root} root={root} />
        ))}
      </Stack>
    </Card>
  );
}
