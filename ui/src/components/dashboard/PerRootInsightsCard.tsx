import { Badge, Card, Group, ScrollArea, Table, Text } from "@mantine/core";
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

export default function PerRootInsightsCard() {
  const [rootInsights, setRootInsights] = useState<RootInsight[]>([]);
  const [rootInsightsTruncated, setRootInsightsTruncated] = useState(false);
  const [rootInsightsLoaded, setRootInsightsLoaded] = useState(false);
  const [rootInsightsError, setRootInsightsError] = useState<string | null>(null);

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

  return (
    <Card withBorder>
      <Group justify="space-between" mb="xs">
        <Text fw={600}>Per Root Insights</Text>
        <Badge color={rootInsightsTruncated ? "yellow" : "blue"}>
          {rootInsights.length} roots
        </Badge>
      </Group>
      <Text size="sm" c="dimmed" mb="sm">
        Directory-level health and progress grouped by library/shadow root.
        {rootInsightsTruncated ? " Results are truncated at 5000 mapped directories." : ""}
      </Text>
      {rootInsightsError ? (
        <Text size="xs" c="yellow" mb="sm">
          {rootInsightsError}
        </Text>
      ) : null}
      <ScrollArea type="auto" scrollbars="x">
        <Table
          highlightOnHover
          withTableBorder
          withColumnBorders
          style={{ tableLayout: "fixed", minWidth: "62rem" }}
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th style={{ width: "24rem" }}>Root</Table.Th>
              <Table.Th style={{ width: "7rem" }}>Dirs</Table.Th>
              <Table.Th style={{ width: "8rem" }}>Arr OK</Table.Th>
              <Table.Th style={{ width: "9rem" }}>Not In Arr</Table.Th>
              <Table.Th style={{ width: "11rem" }}>Missing Target</Table.Th>
              <Table.Th style={{ width: "11rem" }}>Reconcile Failed</Table.Th>
              <Table.Th style={{ width: "8rem" }}>Updated</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rootInsights.map((insight) => (
              <Table.Tr key={insight.shadowRoot}>
                <Table.Td>
                  <Text
                    size="sm"
                    c="dimmed"
                    style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                    title={insight.shadowRoot}
                  >
                    {insight.shadowRoot}
                  </Text>
                </Table.Td>
                <Table.Td>{insight.directoriesTotal}</Table.Td>
                <Table.Td>{insight.arrOk}</Table.Td>
                <Table.Td>{insight.notInArr}</Table.Td>
                <Table.Td>{insight.missingTarget}</Table.Td>
                <Table.Td>{insight.reconcileFailed}</Table.Td>
                <Table.Td>
                  {insight.updatedAtMs == null
                    ? "-"
                    : formatAge(Math.floor(insight.updatedAtMs / 1000))}
                </Table.Td>
              </Table.Tr>
            ))}
            {rootInsightsLoaded && rootInsights.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={7}>
                  <Text size="sm" c="dimmed">No mapped directories indexed yet.</Text>
                </Table.Td>
              </Table.Tr>
            ) : null}
          </Table.Tbody>
        </Table>
      </ScrollArea>
    </Card>
  );
}
