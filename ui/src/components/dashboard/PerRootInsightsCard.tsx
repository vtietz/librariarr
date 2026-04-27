import { Badge, Card, Group, Loader, Progress, Skeleton, Stack, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { getMappedDirectories } from "../../api/client";
import { formatAge } from "../dashboardFormatters";

type MappedDirectoryEntry = Awaited<ReturnType<typeof getMappedDirectories>>["items"][number];

type RootInsight = {
  shadowRoot: string;
  directoriesTotal: number;
  arrOk: number;
  notInArr: number;
  missingTarget: number;
  reconcileFailed: number;
  updatedAtMs: number | null;
};

function buildPerRootInsights(items: MappedDirectoryEntry[]): RootInsight[] {
  const byRoot = new Map<string, RootInsight>();

  for (const item of items) {
    const shadowRoot = String(item.shadow_root ?? "");
    if (!shadowRoot) {
      continue;
    }

    const current = byRoot.get(shadowRoot) ?? {
      shadowRoot,
      directoriesTotal: 0,
      arrOk: 0,
      notInArr: 0,
      missingTarget: 0,
      reconcileFailed: 0,
      updatedAtMs: null,
    };

    current.directoriesTotal += 1;

    const arrState = String(item.arr_state ?? "");
    if (arrState === "ok" || arrState === "title_path_mismatch") {
      current.arrOk += 1;
    }
    if (arrState === "missing_in_arr") {
      current.notInArr += 1;
    }
    if (!item.target_exists || arrState === "missing_on_disk") {
      current.missingTarget += 1;
    }

    const lastStatus = String(item.last_reconcile_status ?? "");
    if (lastStatus === "arr_unreachable" || lastStatus === "reconcile_failed") {
      current.reconcileFailed += 1;
    }

    if (typeof item.last_reconcile_updated_at_ms === "number") {
      current.updatedAtMs =
        current.updatedAtMs == null
          ? item.last_reconcile_updated_at_ms
          : Math.max(current.updatedAtMs, item.last_reconcile_updated_at_ms);
    }

    byRoot.set(shadowRoot, current);
  }

  return Array.from(byRoot.values()).sort((left, right) =>
    left.shadowRoot.localeCompare(right.shadowRoot)
  );
}

function rootDisplayName(shadowRoot: string): string {
  return shadowRoot.replace(/\/+$/, "") || shadowRoot;
}

export default function PerRootInsightsCard() {
  const [rootInsights, setRootInsights] = useState<RootInsight[]>([]);
  const [rootInsightsTruncated, setRootInsightsTruncated] = useState(false);
  const [rootInsightsLoaded, setRootInsightsLoaded] = useState(false);
  const [rootInsightsError, setRootInsightsError] = useState<string | null>(null);
  const [configuredRoots, setConfiguredRoots] = useState<string[]>([]);

  useEffect(() => {
    let active = true;
    let inFlight = false;

    const loadRootInsights = async () => {
      if (inFlight) {
        return;
      }
      inFlight = true;
      try {
        let payload: Awaited<ReturnType<typeof getMappedDirectories>>;
        try {
          payload = await getMappedDirectories({
            includeArrState: true,
            limit: 5000,
            timeoutMs: 30000,
          });
          if (active) {
            setRootInsightsError(null);
          }
        } catch {
          // Fall back to cache-only mapped directories when Arr enrichment times out.
          payload = await getMappedDirectories({
            includeArrState: false,
            limit: 5000,
            timeoutMs: 30000,
          });
          if (active) {
            setRootInsightsError("Arr enrichment unavailable; showing mapped-directory snapshot.");
          }
        }
        if (!active) {
          return;
        }
        setRootInsights(buildPerRootInsights(payload.items));
        setRootInsightsTruncated(Boolean(payload.truncated));
        if (payload.shadow_roots?.length) {
          setConfiguredRoots(payload.shadow_roots);
        }
        setRootInsightsLoaded(true);
      } catch {
        if (active) {
          setRootInsightsError("Failed to load mapped directories for root insights.");
          setRootInsightsLoaded(true);
        }
      } finally {
        inFlight = false;
      }
    };

    void loadRootInsights();
    const interval = window.setInterval(() => {
      void loadRootInsights();
    }, 10000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  // Merge configured roots with loaded insights so roots appear immediately
  const insightRoots = new Set(rootInsights.map((i) => i.shadowRoot));
  const pendingRoots = configuredRoots
    .filter((root) => !insightRoots.has(root))
    .sort((a, b) => a.localeCompare(b));
  const displayRootCount = rootInsights.length + pendingRoots.length;

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Group gap="xs">
          <Text fw={600}>Library Roots</Text>
          {!rootInsightsLoaded && <Loader size="xs" />}
        </Group>
        <Badge color={rootInsightsTruncated ? "yellow" : "blue"} size="sm">
          {displayRootCount} roots
        </Badge>
      </Group>
      {rootInsightsError ? (
        <Text size="xs" c="yellow" mb="sm">
          {rootInsightsError}
        </Text>
      ) : null}
      <Stack gap="md">
        {rootInsights.map((insight) => {
          const total = insight.directoriesTotal || 1;
          const okPct = (insight.arrOk / total) * 100;
          const notInArrPct = (insight.notInArr / total) * 100;
          const issueCount = insight.missingTarget + insight.reconcileFailed;
          const issuePct = (issueCount / total) * 100;

          return (
            <Stack key={insight.shadowRoot} gap={4}>
              <Group justify="space-between">
                <Text size="sm" fw={500} title={insight.shadowRoot}>
                  {rootDisplayName(insight.shadowRoot)}
                </Text>
                <Group gap="xs">
                  <Text size="xs" c="dimmed">
                    {insight.directoriesTotal} dirs
                  </Text>
                  {insight.updatedAtMs != null && (
                    <Text size="xs" c="dimmed">
                      · {formatAge(Math.floor(insight.updatedAtMs / 1000))}
                    </Text>
                  )}
                </Group>
              </Group>
              <Progress.Root size="lg">
                <Progress.Section value={okPct} color="teal" />
                {notInArrPct > 0 && (
                  <Progress.Section value={notInArrPct} color="yellow" />
                )}
                {issuePct > 0 && (
                  <Progress.Section value={issuePct} color="red" />
                )}
              </Progress.Root>
              <Group gap="md">
                <Text size="xs" c="dimmed">
                  <Text span c="teal" fw={600}>●</Text> {insight.arrOk} synced
                </Text>
                {insight.notInArr > 0 && (
                  <Text size="xs" c="dimmed">
                    <Text span c="yellow" fw={600}>●</Text> {insight.notInArr} not in arr
                  </Text>
                )}
                {issueCount > 0 && (
                  <Text size="xs" c="dimmed">
                    <Text span c="red" fw={600}>●</Text> {issueCount} issues
                  </Text>
                )}
              </Group>
            </Stack>
          );
        })}
        {pendingRoots.map((root) => (
          <Stack key={root} gap={4}>
            <Text size="sm" fw={500}>
              {rootDisplayName(root)}
            </Text>
            <Skeleton height={8} radius="xl" />
            <Text size="xs" c="dimmed">
              Loading…
            </Text>
          </Stack>
        ))}
        {rootInsightsLoaded && displayRootCount === 0 && (
          <Text size="sm" c="dimmed">
            No mapped directories indexed yet.
          </Text>
        )}
      </Stack>
    </Card>
  );
}
