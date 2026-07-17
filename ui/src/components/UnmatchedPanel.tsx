import { Alert, Badge, Button, Group, Stack, Table, Text } from "@mantine/core";
import { useState } from "react";
import type { ManualAddResult, UnmatchedEntry } from "../api/client";
import { manualAdd } from "../api/client";

const REASON_HINTS: Record<string, string> = {
  auto_add_disabled: "Auto-add is disabled or has no quality profile configured.",
  ambiguous:
    "Multiple Arr matches. Add the title in the Radarr/Sonarr UI; it links on the next full pass.",
  no_match: "No Arr lookup match. Add the title manually in the Radarr/Sonarr UI.",
  lookup_failed: "Arr lookup failed; will retry on the next full pass.",
  add_failed: "The Arr API rejected the add — see the details column.",
  unparseable: "Folder name could not be parsed as 'Title (Year)'.",
  duplicate:
    "The matching Arr entry is already synced from another managed folder — this looks like a second copy.",
  already_in_arr:
    "The title already exists in Arr but cannot be linked automatically — see the details column."
};

const formatTime = (epochSeconds: number | null): string =>
  epochSeconds ? new Date(epochSeconds * 1000).toLocaleString() : "never";

export default function UnmatchedPanel({
  unmatched,
  asOf,
  onRunFullPass,
  onRefresh
}: {
  unmatched: UnmatchedEntry[];
  asOf: number | null;
  onRunFullPass: () => void;
  onRefresh: () => void;
}) {
  const [results, setResults] = useState<Record<string, ManualAddResult | "pending">>({});

  const tryAdd = async (path: string) => {
    setResults((current) => ({ ...current, [path]: "pending" }));
    try {
      const result = await manualAdd(path);
      setResults((current) => ({ ...current, [path]: result }));
      if (result.ok) {
        onRefresh();
      }
    } catch (error) {
      setResults((current) => ({
        ...current,
        [path]: { ok: false, reason: "error", detail: String(error) }
      }));
    }
  };

  const header = (
    <Group justify="space-between">
      <Text size="sm" c="dimmed">
        Discovery runs during <b>full passes</b> only (webhook/consistency passes don't scan
        folders). This list is from the last full pass: <b>{formatTime(asOf)}</b>.
      </Text>
      <Button size="xs" variant="light" onClick={onRunFullPass}>
        Run full pass now
      </Button>
    </Group>
  );

  if (unmatched.length === 0) {
    return (
      <Stack gap="sm">
        {header}
        <Alert color="green">
          No unmatched folders{asOf ? " — every managed folder is linked to an Arr entry." : "."}
          {!asOf && " Run a full pass to scan the managed tree."}
        </Alert>
      </Stack>
    );
  }

  return (
    <Stack gap="sm">
      {header}
      <Text size="sm" c="dimmed">
        To resolve: click <b>Try add</b> (uses the exact parsed title/year), or add the title
        yourself in the Radarr/Sonarr UI — the next full pass links it automatically.
      </Text>
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Folder</Table.Th>
            <Table.Th>Parsed</Table.Th>
            <Table.Th>Reason</Table.Th>
            <Table.Th>Details</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {unmatched.map((entry) => {
            const result = results[entry.path];
            return (
              <Table.Tr key={entry.path}>
                <Table.Td style={{ wordBreak: "break-all" }}>{entry.path}</Table.Td>
                <Table.Td>
                  {entry.parsed_title ?? "–"}
                  {entry.parsed_year ? ` (${entry.parsed_year})` : ""}
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" title={REASON_HINTS[entry.reason] ?? ""}>
                    {entry.reason}
                  </Badge>
                </Table.Td>
                <Table.Td style={{ maxWidth: 320 }}>
                  {result && result !== "pending" && !result.ok && (
                    <Text size="xs" c="red">
                      {result.reason}
                      {result.detail ? `: ${result.detail}` : ""}
                      {result.candidates?.length
                        ? ` — candidates: ${result.candidates.join(", ")}`
                        : ""}
                    </Text>
                  )}
                  {result && result !== "pending" && result.ok && (
                    <Text size="xs" c="green">
                      Added — it disappears from this list after the next full pass.
                    </Text>
                  )}
                  {!result && (
                    <Text size="xs" c="dimmed">
                      {entry.candidates.join(", ")}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Button
                    size="xs"
                    variant="light"
                    loading={result === "pending"}
                    disabled={result !== undefined && result !== "pending" && result.ok}
                    onClick={() => tryAdd(entry.path)}
                  >
                    Try add
                  </Button>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
