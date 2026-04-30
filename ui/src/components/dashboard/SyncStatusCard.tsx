import { Badge, Button, Card, Group, Loader, Stack, Text, ThemeIcon } from "@mantine/core";
import { IconCheck, IconCircleDot, IconClock } from "@tabler/icons-react";
import type { RuntimeStatusResponse } from "../../api/client";
import { formatAge, formatElapsed } from "../dashboardFormatters";

type Props = {
  hasUnsavedChanges: boolean;
  runtimeStatus: RuntimeStatusResponse | null;
  runningReconcile: boolean;
  onRunFullReconcile: () => Promise<void>;
};

function healthBadgeColor(status: string): string {
  if (status === "ok") return "green";
  if (status === "degraded") return "yellow";
  return "gray";
}

function stateBadgeColor(state: string): string {
  if (state === "running") return "blue";
  if (state === "error") return "red";
  return "gray";
}

// ── Step Pipeline ──────────────────────────────────────────────────────

type StepDef = {
  id: string;
  label: string;
  phases: string[];
};

const SYNC_STEPS: StepDef[] = [
  {
    id: "fetch",
    label: "Fetch inventory",
    phases: [
      "reconcile",
      "full_reconcile",
      "startup_full_reconcile",
      "startup_incremental_reconcile",
      "running",
      "inventory_fetched",
    ],
  },
  { id: "ingest", label: "Ingest library changes", phases: ["ingest_movies"] },
  { id: "scope", label: "Resolve scope", phases: ["scope_resolved"] },
  { id: "plan", label: "Plan projections", phases: ["planning_movies", "planning_series"] },
  {
    id: "autoadd",
    label: "Resolve unmatched (Arr API)",
    phases: ["auto_add_movies", "auto_add_series"],
  },
  { id: "apply", label: "Apply hardlinks", phases: ["indexed", "applied"] },
  { id: "cleanup", label: "Cleanup", phases: ["cleaned", "completed"] },
];

type StepState = "pending" | "active" | "done";

function stripFolderCounterSuffix(label: string): string {
  return label.replace(/\s*\(\d+\/\d+\s+folders\)$/i, "");
}

function resolveStepStates(
  phase: string | null | undefined,
  isRunning: boolean,
): StepState[] {
  if (!phase) {
    return SYNC_STEPS.map((_, i) => (isRunning && i === 0 ? "active" : "pending"));
  }

  let activeIdx = -1;
  for (let i = 0; i < SYNC_STEPS.length; i++) {
    if (SYNC_STEPS[i].phases.includes(phase)) {
      activeIdx = i;
      break;
    }
  }

  if (activeIdx === -1) {
    return SYNC_STEPS.map((_, i) => (isRunning && i === 0 ? "active" : "pending"));
  }

  return SYNC_STEPS.map((_, i) => {
    if (i < activeIdx) return "done";
    if (i === activeIdx) return "active";
    return "pending";
  });
}

function phaseExplanation(task: RuntimeStatusResponse["current_task"]): string | null {
  if (task.state !== "running") return null;

  const phase = task.phase;
  if (!phase) return "Preparing reconcile";

  const map: Record<string, string> = {
    reconcile: "Fetching movie/series inventory from Radarr/Sonarr",
    startup_full_reconcile: "Starting initial full reconcile",
    running: "Starting reconcile",
    inventory_fetched: "Inventory fetched; preparing scope",
    ingest_movies: "Checking library-root items and ingesting to managed roots",
    scope_resolved: "Scope resolved (deciding full vs incremental items)",
    planning_movies: "Planning movie projections",
    planning_series: "Planning series projections",
    auto_add_movies: "Resolving unmatched movie folders via Radarr API",
    auto_add_series: "Resolving unmatched series folders via Sonarr API",
    indexed: "Applying hardlinks for planned projections",
    applied: "Projection apply complete",
    cleaned: "Cleanup in progress",
    completed: "Reconcile complete",
  };

  return map[phase] ?? `Running phase: ${phase}`;
}

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") {
    return (
      <ThemeIcon size={16} radius="xl" color="teal" variant="filled">
        <IconCheck size={10} />
      </ThemeIcon>
    );
  }
  if (state === "active") {
    return (
      <ThemeIcon size={16} radius="xl" color="blue" variant="filled">
        <IconCircleDot size={10} />
      </ThemeIcon>
    );
  }
  return (
    <ThemeIcon size={16} radius="xl" color="gray" variant="light">
      <IconClock size={10} />
    </ThemeIcon>
  );
}

function SyncStepPipeline({
  phase,
  isRunning,
}: {
  phase: string | null | undefined;
  isRunning: boolean;
}) {
  const states = resolveStepStates(phase, isRunning);
  return (
    <Group gap={6} wrap="wrap">
      {SYNC_STEPS.map((step, i) => (
        <Group key={step.id} gap={3} wrap="nowrap">
          <StepIcon state={states[i]} />
          <Text
            size="xs"
            c={states[i] === "active" ? "blue" : states[i] === "done" ? "teal" : "dimmed"}
            fw={states[i] === "active" ? 600 : 400}
          >
            {stripFolderCounterSuffix(step.label)}
          </Text>
          {i < SYNC_STEPS.length - 1 && (
            <Text size="xs" c="dimmed">›</Text>
          )}
        </Group>
      ))}
    </Group>
  );
}

// ── Progress detail ────────────────────────────────────────────────────

function buildProgressDetail(
  task: RuntimeStatusResponse["current_task"],
): string | null {
  if (task.state !== "running") return null;

  const parts: string[] = [];

  const moviesSeen = task.movie_folders_seen ?? 0;
  const seriesSeen = task.series_folders_seen ?? 0;
  if (moviesSeen > 0 || seriesSeen > 0) {
    const items: string[] = [];
    if (moviesSeen > 0) items.push(`${moviesSeen} movies`);
    if (seriesSeen > 0) items.push(`${seriesSeen} series`);
    parts.push(items.join(", "));
  }

  const links = task.created_links ?? 0;
  if (links > 0) parts.push(`${links} links created`);

  const phase = task.phase;
  const movieProcessed = task.movie_items_processed ?? 0;
  const movieTotal = task.movie_items_total ?? 0;
  const seriesProcessed = task.series_items_processed ?? 0;
  const seriesTotal = task.series_items_total ?? 0;

  const movieCounter = movieTotal > 0 ? `${movieProcessed}/${movieTotal} movies` : null;
  const seriesCounter = seriesTotal > 0 ? `${seriesProcessed}/${seriesTotal} series` : null;

  let phaseCounter: string | null = null;
  if (
    phase === "ingest_movies" ||
    phase === "planning_movies" ||
    phase === "auto_add_movies" ||
    phase === "indexed"
  ) {
    phaseCounter = movieCounter;
  } else if (phase === "planning_series" || phase === "auto_add_series") {
    phaseCounter = seriesCounter;
  }

  if (phaseCounter) {
    parts.push(phaseCounter);
  }

  if (task.started_at) {
    parts.push(formatElapsed(task.started_at));
  }

  return parts.length > 0 ? parts.join(" · ") : null;
}

function buildLastSyncText(
  lastReconcile: RuntimeStatusResponse["last_reconcile"],
): string {
  if (!lastReconcile?.finished_at) {
    return "No completed sync yet";
  }

  const parts = [`Last sync ${formatAge(lastReconcile.finished_at)}`];

  if (typeof lastReconcile.duration_seconds === "number") {
    parts.push(`${lastReconcile.duration_seconds.toFixed(1)}s`);
  }

  const createdLinks = lastReconcile.created_links ?? 0;
  if (createdLinks > 0) {
    parts.push(`${createdLinks} links created`);
  }

  const stats = lastReconcile.full_reconcile_stats;
  if (stats) {
    const projected = stats.total_projected_files;
    if (typeof projected === "number") {
      parts.push(`${projected} files projected`);
    }
    const autoAdded =
      Number(stats.auto_added_movies ?? 0) + Number(stats.auto_added_series ?? 0);
    if (autoAdded > 0) {
      parts.push(`${autoAdded} auto-added`);
    }
    const ingested = Number(stats.ingested_movies ?? 0);
    if (ingested > 0) {
      parts.push(`${ingested} ingested`);
    }
  }

  return parts.join(" · ");
}

export default function SyncStatusCard({
  hasUnsavedChanges,
  runtimeStatus,
  runningReconcile,
  onRunFullReconcile,
}: Props) {
  const healthStatus = runtimeStatus?.health?.status ?? "starting";
  const healthReason = runtimeStatus?.health?.reasons?.[0] ?? "Waiting for status";
  const taskState = runtimeStatus?.current_task.state ?? "idle";
  const lastSyncText = buildLastSyncText(runtimeStatus?.last_reconcile ?? null);
  const currentTask = runtimeStatus?.current_task ?? {
    state: "idle" as const,
    phase: null,
    trigger_source: null,
    started_at: null,
    updated_at: null,
    error: null,
  };
  const progressDetail = buildProgressDetail(currentTask);
  const phaseDetail = phaseExplanation(currentTask);
  const isRunning = currentTask.state === "running";

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Sync Status</Text>
        <Group gap="xs">
          <Badge color={healthBadgeColor(healthStatus)} size="sm">
            {healthStatus}
          </Badge>
          <Badge
            color={hasUnsavedChanges ? "yellow" : "green"}
            size="sm"
            variant="light"
          >
            {hasUnsavedChanges ? "config unsaved" : "config synced"}
          </Badge>
          <Badge color={stateBadgeColor(taskState)} size="sm">
            {taskState}
          </Badge>
        </Group>
      </Group>
      <Stack gap={4}>
        <Text size="sm" c="dimmed">
          {healthReason}
        </Text>
        {isRunning && (
          <SyncStepPipeline phase={currentTask.phase} isRunning={isRunning} />
        )}
        {phaseDetail && (
          <Text size="xs" c="dimmed">
            {phaseDetail}
          </Text>
        )}
        {progressDetail && (
          <Group gap="xs" align="flex-start" wrap="nowrap">
            <Loader size={12} />
            <Text
              size="xs"
              c="blue"
              style={{ whiteSpace: "normal", lineHeight: 1.35, wordBreak: "break-word" }}
            >
              {progressDetail}
            </Text>
          </Group>
        )}
        <Group justify="space-between" align="center" wrap="wrap" gap="xs">
          <Text size="xs" c="dimmed" style={{ flex: "1 1 16rem" }}>
            {lastSyncText}
          </Text>
          <Button
            size="compact-xs"
            variant="light"
            loading={runningReconcile}
            onClick={() => void onRunFullReconcile()}
          >
            Run Full Reconcile
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
