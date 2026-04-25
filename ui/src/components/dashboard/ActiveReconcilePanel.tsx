import { Badge, Button, Card, Group, Stack, Text } from "@mantine/core";
import type { RuntimeStatusResponse } from "../../api/client";
import { formatAge, formatCoverage } from "../dashboardFormatters";

type Props = {
  runtimeStatus: RuntimeStatusResponse | null;
  runningReconcile: boolean;
  onRunFullReconcile: () => Promise<void>;
};

function summarizeScope(metrics: {
  active_movie_root?: string | null;
  active_series_root?: string | null;
  movie_folders_seen?: number;
  series_folders_seen?: number;
  affected_paths_count?: number | null;
} | null | undefined): string | null {
  if (!metrics) {
    return null;
  }
  const hasMovieCount = typeof metrics.movie_folders_seen === "number";
  const hasSeriesCount = typeof metrics.series_folders_seen === "number";
  if (!hasMovieCount && !hasSeriesCount) {
    return null;
  }

  const modeText =
    typeof metrics.affected_paths_count === "number"
      ? `incremental (${metrics.affected_paths_count} affected paths)`
      : "full";
  const movieCount = hasMovieCount ? metrics.movie_folders_seen : 0;
  const seriesCount = hasSeriesCount ? metrics.series_folders_seen : 0;
  const movieRootText = metrics.active_movie_root
    ? ` · movie root ${metrics.active_movie_root}`
    : "";
  const seriesRootText = metrics.active_series_root
    ? ` · series root ${metrics.active_series_root}`
    : "";

  return `${modeText} · considered folders M/S ${movieCount}/${seriesCount}${movieRootText}${seriesRootText}`;
}

export default function ActiveReconcilePanel({
  runtimeStatus,
  runningReconcile,
  onRunFullReconcile,
}: Props) {
  const taskState = runtimeStatus?.current_task.state ?? "idle";
  const statusBadgeColor =
    taskState === "running" ? "blue" : taskState === "error" ? "red" : "gray";

  const snapshotMetrics =
    taskState === "running" ? runtimeStatus?.current_task : runtimeStatus?.last_reconcile;

  const snapshotMatchedMovies = snapshotMetrics?.matched_movies;
  const snapshotUnmatchedMovies = snapshotMetrics?.unmatched_movies;
  const snapshotMatchedSeries = snapshotMetrics?.matched_series;
  const snapshotUnmatchedSeries = snapshotMetrics?.unmatched_series;

  const snapshotCreatedLinks =
    snapshotMetrics?.created_links ?? runtimeStatus?.last_reconcile?.created_links ?? 0;

  const snapshotMoviePending =
    typeof snapshotMetrics?.movie_items_targeted === "number" &&
    typeof snapshotMetrics?.movie_items_projected === "number"
      ? Math.max(0, snapshotMetrics.movie_items_targeted - snapshotMetrics.movie_items_projected)
      : null;

  const snapshotSeriesPending =
    typeof snapshotMetrics?.series_items_targeted === "number" &&
    typeof snapshotMetrics?.series_items_projected === "number"
      ? Math.max(0, snapshotMetrics.series_items_targeted - snapshotMetrics.series_items_projected)
      : null;

  const movieCoverage = formatCoverage(snapshotMatchedMovies, snapshotUnmatchedMovies);
  const seriesCoverage = formatCoverage(snapshotMatchedSeries, snapshotUnmatchedSeries);

  const scopeSummary = summarizeScope(
    taskState === "running" ? runtimeStatus?.current_task : runtimeStatus?.last_reconcile
  );

  const lastFinishedAt = runtimeStatus?.last_reconcile?.finished_at;
  const lastReconcileMeta =
    lastFinishedAt == null
      ? "no completed reconcile yet"
      : `last completed ${formatAge(lastFinishedAt)} · duration ${runtimeStatus?.last_reconcile?.duration_seconds ?? 0}s`;

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Active Reconcile</Text>
        <Group gap="xs">
          <Badge color={statusBadgeColor}>{taskState}</Badge>
          <Button
            size="compact-xs"
            variant="light"
            loading={runningReconcile}
            onClick={() => void onRunFullReconcile()}
          >
            Run Full Reconcile
          </Button>
        </Group>
      </Group>

      <Stack gap={6}>
        <Text size="sm" c="dimmed">
          {scopeSummary ?? "Waiting for next reconcile cycle"}
        </Text>
        <Text size="sm" c="dimmed">
          Movies {movieCoverage} · unmatched {typeof snapshotUnmatchedMovies === "number" ? snapshotUnmatchedMovies : "n/a"}
          {" · "}
          Series {seriesCoverage} · unmatched {typeof snapshotUnmatchedSeries === "number" ? snapshotUnmatchedSeries : "n/a"}
        </Text>
        <Text size="sm" c="dimmed">
          Indexed M/S: {typeof snapshotMetrics?.movie_folders_seen === "number" ? snapshotMetrics.movie_folders_seen : "n/a"}/
          {typeof snapshotMetrics?.series_folders_seen === "number" ? snapshotMetrics.series_folders_seen : "n/a"}
          {" · "}
          pending M/S: {snapshotMoviePending ?? "n/a"}/{snapshotSeriesPending ?? "n/a"}
          {" · "}
          created links {snapshotCreatedLinks}
        </Text>
        <Text size="xs" c="dimmed">{lastReconcileMeta}</Text>
        <Text size="xs" c="dimmed">
          Runtime reconcile is single-worker; cache/discovery rebuild tasks may run in parallel.
        </Text>
      </Stack>
    </Card>
  );
}
