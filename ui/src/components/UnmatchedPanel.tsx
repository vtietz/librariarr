import { Alert, Badge, Stack, Table, Text } from "@mantine/core";
import type { UnmatchedEntry } from "../api/client";

const REASON_HINTS: Record<string, string> = {
  auto_add_disabled: "Auto-add is disabled or has no quality profile configured.",
  ambiguous: "Multiple Arr matches. Add the title in the Radarr/Sonarr UI; it links on the next full pass.",
  no_match: "No Arr lookup match. Add the title manually in the Radarr/Sonarr UI.",
  lookup_failed: "Arr lookup failed; will retry on the next full pass.",
  add_failed: "Arr rejected auto-add for this title; check Arr logs/details and retry.",
  unparseable: "Folder name could not be parsed as 'Title (Year)'."
};

export default function UnmatchedPanel({ unmatched }: { unmatched: UnmatchedEntry[] }) {
  if (unmatched.length === 0) {
    return (
      <Stack gap="sm">
        <Alert color="green">No unmatched folders in the latest full discovery pass.</Alert>
        <Text size="sm" c="dimmed">
          "Unmatched" only includes managed folders that LibrariArr could not map to Arr. It does
          not mean every managed file exists in TMDb/IMDb, and it is refreshed by full passes.
        </Text>
      </Stack>
    );
  }
  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        These are managed folders that currently cannot be linked or auto-added in Arr.
      </Text>
      <Text size="sm" c="dimmed">
        To resolve an entry, add the title in the Radarr/Sonarr UI (no paths needed). The next
        full pass links it to the managed folder automatically.
      </Text>
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Folder</Table.Th>
            <Table.Th>Parsed</Table.Th>
            <Table.Th>Reason</Table.Th>
            <Table.Th>Candidates</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {unmatched.map((entry) => (
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
              <Table.Td>{entry.candidates.join(", ")}</Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}
