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

/**
 * Derive matched/unmatched totals from per-root stats.
 * This is always up-to-date (updated during projection) and reflects
 * the full library, unlike incremental reconcile metrics which are scoped.
 */
function statsFromRoots(
  roots: NonNullable<RuntimeStatusResponse["library_root_stats"]>,
  arrType: "radarr" | "sonarr",
): { matched: number; unmatched: number } | null {
  const filtered = roots.filter((r) => r.arr_type === arrType);
  if (filtered.length === 0) return null;
  let matched = 0;
  let unmatched = 0;
  for (const r of filtered) {
    matched += r.matched;
    unmatched += r.skipped;
  }
  return { matched, unmatched };
}

export default function LibraryStatsCards({ runtimeStatus }: Props) {
  const fullReconcile = runtimeStatus?.last_full_reconcile ?? null;
  const currentTask =
    runtimeStatus?.current_task.state === "running"
      ? runtimeStatus.current_task
      : null;
  const lastReconcile = runtimeStatus?.last_reconcile ?? null;
  const roots = runtimeStatus?.library_root_stats ?? [];

  // Primary source: per-root stats (always current, updated live during projection)
  const movieRootStats = statsFromRoots(roots, "radarr");
  const seriesRootStats = statsFromRoots(roots, "sonarr");

  // Fallback: reconcile-level metrics (full reconcile preferred)
  const hasFullMetrics =
    fullReconcile != null &&
    (typeof fullReconcile.matched_movies === "number" ||
      typeof fullReconcile.matched_series === "number");
  const hasCurrentMetrics =
    currentTask != null &&
    (typeof currentTask.matched_movies === "number" ||
      typeof currentTask.matched_series === "number");
  const reconcileMetrics = hasFullMetrics
    ? fullReconcile
    : hasCurrentMetrics
      ? currentTask
      : lastReconcile;

  // Use per-root stats when available, otherwise fall back to reconcile metrics
  const movieMatched = movieRootStats?.matched ?? reconcileMetrics?.matched_movies;
  const movieUnmatched = movieRootStats?.unmatched ?? reconcileMetrics?.unmatched_movies;
  const seriesMatched = seriesRootStats?.matched ?? reconcileMetrics?.matched_series;
  const seriesUnmatched = seriesRootStats?.unmatched ?? reconcileMetrics?.unmatched_series;

  const movieInProgress =
    currentTask != null &&
    movieMatched === undefined &&
    movieUnmatched === undefined
      ? {
          seen: currentTask.movie_folders_seen ?? 0,
          projected: currentTask.movie_items_projected ?? 0,
        }
      : null;
  const seriesInProgress =
    currentTask != null &&
    seriesMatched === undefined &&
    seriesUnmatched === undefined
      ? {
          seen: currentTask.series_folders_seen ?? 0,
          projected: currentTask.series_items_projected ?? 0,
        }
      : null;

  return (
    <SimpleGrid cols={{ base: 1, sm: 2 }}>
      <CoverageCard
        label="Movies"
        matched={movieMatched}
        unmatched={movieUnmatched}
        inProgress={movieInProgress}
      />
      <CoverageCard
        label="Series"
        matched={seriesMatched}
        unmatched={seriesUnmatched}
        inProgress={seriesInProgress}
      />
    </SimpleGrid>
  );
}
