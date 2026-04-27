import { Card, Group, RingProgress, SimpleGrid, Stack, Text } from "@mantine/core";
import type { RuntimeStatusResponse } from "../../api/client";

type Props = {
  runtimeStatus: RuntimeStatusResponse | null;
};

function coverageColor(pct: number): string {
  if (pct >= 90) {
    return "teal";
  }
  if (pct >= 70) {
    return "yellow";
  }
  return "red";
}

function CoverageCard({
  label,
  matched,
  unmatched,
}: {
  label: string;
  matched: number | undefined;
  unmatched: number | undefined;
}) {
  const matchedVal = typeof matched === "number" ? matched : 0;
  const unmatchedVal = typeof unmatched === "number" ? unmatched : 0;
  const total = matchedVal + unmatchedVal;
  const pct = total > 0 ? Math.round((matchedVal / total) * 100) : 0;
  const hasData = typeof matched === "number" || typeof unmatched === "number";

  return (
    <Card withBorder>
      <Group wrap="nowrap" gap="md">
        <RingProgress
          size={80}
          thickness={8}
          roundCaps
          sections={hasData ? [{ value: pct, color: coverageColor(pct) }] : []}
          label={
            <Text size="xs" ta="center" fw={700}>
              {hasData ? `${pct}%` : "–"}
            </Text>
          }
        />
        <Stack gap={2}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            {label}
          </Text>
          {hasData ? (
            <>
              <Group gap={4} align="baseline">
                <Text size="xl" fw={700} lh={1}>
                  {matchedVal}
                </Text>
                <Text size="sm" c="dimmed">
                  / {total}
                </Text>
              </Group>
              {unmatchedVal > 0 ? (
                <Text size="xs" c="yellow">
                  {unmatchedVal} unmatched
                </Text>
              ) : (
                total > 0 && (
                  <Text size="xs" c="teal">
                    all matched
                  </Text>
                )
              )}
            </>
          ) : (
            <Text size="sm" c="dimmed">
              Waiting for data
            </Text>
          )}
        </Stack>
      </Group>
    </Card>
  );
}

export default function LibraryStatsCards({ runtimeStatus }: Props) {
  const currentTask =
    runtimeStatus?.current_task.state === "running"
      ? runtimeStatus.current_task
      : null;
  const lastReconcile = runtimeStatus?.last_reconcile ?? null;

  // Use current task metrics if available, otherwise fall back to last reconcile.
  const hasCurrentMetrics =
    currentTask != null &&
    (typeof currentTask.matched_movies === "number" ||
      typeof currentTask.matched_series === "number");
  const metrics = hasCurrentMetrics ? currentTask : lastReconcile;

  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <CoverageCard
        label="Movies"
        matched={metrics?.matched_movies}
        unmatched={metrics?.unmatched_movies}
      />
      <CoverageCard
        label="Series"
        matched={metrics?.matched_series}
        unmatched={metrics?.unmatched_series}
      />
    </SimpleGrid>
  );
}
