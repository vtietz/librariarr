import { Badge, Card, Group, Progress, Stack, Text, Tooltip } from "@mantine/core";
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

function MetricLabel({
  text,
  color,
  tooltip,
  showDot = true,
}: {
  text: string;
  color?: string;
  tooltip: string;
  showDot?: boolean;
}) {
  return (
    <Tooltip label={tooltip} withArrow>
      <Text size="xs" c="dimmed" style={{ cursor: "help" }}>
        {showDot && color && (
          <Text span c={color} fw={600}>
            ●
          </Text>
        )}{" "}
        {text}
      </Text>
    </Tooltip>
  );
}

function LegendRow() {
  return (
    <Stack gap={4} mb="sm">
      <Group gap="md">
        <Text size="xs" c="dimmed" fw={600}>
          Item outcomes:
        </Text>
        <MetricLabel text="Matched" color="teal" tooltip="Arr item had a valid projection mapping and was processed." />
        <MetricLabel text="Unmatched" color="yellow" tooltip="Arr item was planned but skipped (for example missing folder, no matching managed root, or mapping not actionable)." />
      </Group>
      <Group gap="md">
        <Text size="xs" c="dimmed" fw={600}>
          File outcomes:
        </Text>
        <MetricLabel text="Projected" color="blue" tooltip="Files newly hardlinked in this root during reconcile." />
        <MetricLabel text="Unchanged" color="gray" tooltip="Files already correctly linked and left as-is." />
        <MetricLabel text="Skipped files" color="red" tooltip="Files not linked during apply (for example source missing or preserve-unknown protection)." />
      </Group>
    </Stack>
  );
}

function RootRow({ root }: { root: RootStat }) {
  const total = root.planned || 1;
  const matchedPct = (root.matched / total) * 100;
  const skippedPct = (root.skipped / total) * 100;
  const totalFiles = root.projected_files + root.unchanged_files + root.skipped_files;
  const projectedPct = totalFiles > 0 ? (root.projected_files / totalFiles) * 100 : 0;
  const unchangedPct = totalFiles > 0 ? (root.unchanged_files / totalFiles) * 100 : 0;
  const skippedFilesPct = totalFiles > 0 ? (root.skipped_files / totalFiles) * 100 : 0;

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
        <Progress.Section value={skippedPct} color="yellow" />
      </Progress.Root>

      {totalFiles > 0 && (
        <Progress.Root size="sm">
          <Progress.Section value={projectedPct} color="blue" />
          <Progress.Section value={unchangedPct} color="gray" />
          <Progress.Section value={skippedFilesPct} color="red" />
        </Progress.Root>
      )}

      <Group gap="md">
        <MetricLabel
          text={`${root.matched} matched`}
          color="teal"
          tooltip="Arr items that were successfully matched and processed."
        />
        <MetricLabel
          text={`${root.skipped} unmatched`}
          color="yellow"
          tooltip="Arr items skipped during projection for this root."
        />
        <MetricLabel
          text={`${root.projected_files} projected`}
          color="blue"
          tooltip="Files newly linked during the latest reconcile affecting this root."
        />
        <MetricLabel
          text={`${root.unchanged_files} unchanged`}
          color="gray"
          tooltip="Files already in the desired state and kept untouched."
        />
        <MetricLabel
          text={`${root.skipped_files} skipped files`}
          color="red"
          tooltip="Files that were considered but not linked during apply."
        />
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
      <LegendRow />
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
