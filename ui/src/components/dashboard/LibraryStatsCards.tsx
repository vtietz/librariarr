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
  inProgress,
}: {
  label: string;
  matched: number | undefined;
  unmatched: number | undefined;
  inProgress: { seen: number; projected: number } | null;
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
          ) : inProgress ? (
            <>
              <Group gap={4} align="baseline">
                <Text size="xl" fw={700} lh={1}>
                  {inProgress.seen}
                </Text>
                <Text size="sm" c="dimmed">
                  seen
                </Text>
              </Group>
              <Text size="xs" c="blue">
                {inProgress.projected} projected — syncing…
              </Text>
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
  // Prefer last full reconcile for library-wide coverage stats.
  // Incremental reconciles only report scoped counts (e.g. 1 movie)
  // which would be misleading as overall library metrics.
  const fullReconcile = runtimeStatus?.last_full_reconcile ?? null;
  const currentTask =
    runtimeStatus?.current_task.state === "running"
      ? runtimeStatus.current_task
      : null;
  const lastReconcile = runtimeStatus?.last_reconcile ?? null;

  const hasFullMetrics =
    fullReconcile != null &&
    (typeof fullReconcile.matched_movies === "number" ||
      typeof fullReconcile.matched_series === "number");
  const hasCurrentMetrics =
    currentTask != null &&
    (typeof currentTask.matched_movies === "number" ||
      typeof currentTask.matched_series === "number");
  const metrics = hasFullMetrics
    ? fullReconcile
    : hasCurrentMetrics
      ? currentTask
      : lastReconcile;

  const movieInProgress =
    currentTask != null && !hasFullMetrics && !hasCurrentMetrics
      ? {
          seen: currentTask.movie_folders_seen ?? 0,
          projected: currentTask.movie_items_projected ?? 0,
        }
      : null;
  const seriesInProgress =
    currentTask != null && !hasFullMetrics && !hasCurrentMetrics
      ? {
          seen: currentTask.series_folders_seen ?? 0,
          projected: currentTask.series_items_projected ?? 0,
        }
      : null;

  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <CoverageCard
        label="Movies"
        matched={metrics?.matched_movies}
        unmatched={metrics?.unmatched_movies}
        inProgress={movieInProgress}
      />
      <CoverageCard
        label="Series"
        matched={metrics?.matched_series}
        unmatched={metrics?.unmatched_series}
        inProgress={seriesInProgress}
      />
    </SimpleGrid>
  );
}
