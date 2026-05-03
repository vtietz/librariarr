import { Badge, Card, Group, ScrollArea, Stack, Text } from "@mantine/core";
import { getDiscoveryWarnings } from "../../api/client";

type DiscoveryWarnings = Awaited<ReturnType<typeof getDiscoveryWarnings>>;

type Props = {
  discoveryWarnings: DiscoveryWarnings | null;
};

export default function DiscoveryWarningsCard({ discoveryWarnings }: Props) {
  const excludedCandidates = discoveryWarnings?.summary.excluded_movie_candidates ?? 0;
  const duplicateCandidates = discoveryWarnings?.summary.duplicate_movie_candidates ?? 0;
  const orphanedManagedCandidates =
    discoveryWarnings?.summary.orphaned_managed_movie_candidates ?? 0;
  const excludedItems = discoveryWarnings?.excluded_movie_candidates.slice(0, 6) ?? [];
  const duplicateItems = discoveryWarnings?.duplicate_movie_candidates.slice(0, 6) ?? [];
  const orphanedItems = discoveryWarnings?.orphaned_managed_movie_candidates.slice(0, 6) ?? [];
  const hasDiscoveryWarnings =
    excludedCandidates > 0 || duplicateCandidates > 0 || orphanedManagedCandidates > 0;

  return (
    <Card withBorder>
      <Group justify="space-between">
        <Text fw={600}>Discovery Warnings</Text>
        <Badge color={hasDiscoveryWarnings ? "yellow" : "green"}>
          {hasDiscoveryWarnings ? "needs attention" : "clear"}
        </Badge>
      </Group>
      <Text size="sm" c="dimmed" mt="xs">
        {excludedCandidates} excluded movie candidates · {duplicateCandidates} potential duplicates ·{" "}
        {orphanedManagedCandidates} orphaned managed folders
      </Text>
      {hasDiscoveryWarnings && (
        <ScrollArea mt="xs" type="auto" scrollbars="y" h={220}>
          <Stack gap="sm">
            {excludedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Excluded Candidates ({excludedCandidates})</Text>
                {excludedItems.map((item) => (
                  <Text key={`excluded-${item.path}`} size="xs" c="dimmed">
                    ⚠ {item.path}
                  </Text>
                ))}
              </Stack>
            )}
            {duplicateCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Potential Duplicates ({duplicateCandidates})</Text>
                {duplicateItems.map((item) => (
                  <Text key={`duplicate-${item.primary_path}`} size="xs" c="dimmed">
                    ⚠ {item.movie_ref}: {item.primary_path}
                  </Text>
                ))}
              </Stack>
            )}
            {orphanedManagedCandidates > 0 && (
              <Stack gap={2}>
                <Text size="xs" fw={600}>Orphaned Managed Folders ({orphanedManagedCandidates})</Text>
                {orphanedItems.map((item) => (
                  <Text key={`orphaned-${item.path}`} size="xs" c="dimmed">
                    ⚠ {item.path}
                  </Text>
                ))}
              </Stack>
            )}
          </Stack>
        </ScrollArea>
      )}
    </Card>
  );
}
