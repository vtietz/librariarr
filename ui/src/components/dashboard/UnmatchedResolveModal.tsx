import { Button, Checkbox, Group, Loader, Modal, Radio, Stack, Text } from "@mantine/core";
import type {
  UnmatchedMovieCandidatesResponse,
  UnmatchedMovieWinnerStrategy,
} from "../../api/client";

type Props = {
  opened: boolean;
  path: string | null;
  loading: boolean;
  busyImportPath: string | null;
  candidatesPayload: UnmatchedMovieCandidatesResponse | null;
  selectedMovieId: string;
  onChangeSelectedMovieId: (value: string) => void;
  forceTakeover: boolean;
  onChangeForceTakeover: (value: boolean) => void;
  winnerStrategy: UnmatchedMovieWinnerStrategy;
  onChangeWinnerStrategy: (value: UnmatchedMovieWinnerStrategy) => void;
  quarantineLoser: boolean;
  onChangeQuarantineLoser: (value: boolean) => void;
  error: string;
  onCancel: () => void;
  onConfirm: () => void;
};

export default function UnmatchedResolveModal({
  opened,
  path,
  loading,
  busyImportPath,
  candidatesPayload,
  selectedMovieId,
  onChangeSelectedMovieId,
  forceTakeover,
  onChangeForceTakeover,
  winnerStrategy,
  onChangeWinnerStrategy,
  quarantineLoser,
  onChangeQuarantineLoser,
  error,
  onCancel,
  onConfirm,
}: Props) {
  const conflictingCandidates = (candidatesPayload?.candidates ?? []).filter(
    (candidate) => candidate.mapping_conflict
  );
  const selectedCandidate = (candidatesPayload?.candidates ?? []).find(
    (candidate) => String(candidate.movie_id) === selectedMovieId
  );
  const selectedHasMappingConflict = Boolean(selectedCandidate?.mapping_conflict);

  return (
    <Modal opened={opened} onClose={onCancel} title="Resolve Unmatched Folder" centered size="lg">
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          {path}
        </Text>
        {loading ? (
          <Group justify="center">
            <Loader size="sm" />
          </Group>
        ) : null}
        {candidatesPayload ? (
          <>
            <Text size="sm">
              Pick the Radarr movie to map for this folder, then run a scoped reconcile import.
            </Text>
            {candidatesPayload.nfo_ids.tmdb_id || candidatesPayload.nfo_ids.imdb_id ? (
              <Text size="xs" c="dimmed">
                NFO IDs: tmdb={candidatesPayload.nfo_ids.tmdb_id ?? "-"}, imdb={
                  candidatesPayload.nfo_ids.imdb_id ?? "-"
                }
              </Text>
            ) : null}
            {conflictingCandidates.length > 0 ? (
              <Stack gap={2}>
                <Text size="sm" c="yellow">
                  Possible duplicates detected ({conflictingCandidates.length})
                </Text>
                {conflictingCandidates.map((candidate) => (
                  <Text key={`conflict-${candidate.movie_id}`} size="xs" c="dimmed">
                    {candidate.title}
                    {candidate.year ? ` (${candidate.year})` : ""} is currently mapped to{" "}
                    {candidate.mapped_folder ?? "another managed folder"}
                  </Text>
                ))}
                <Text size="xs" c="dimmed">
                  Use Force takeover only when this folder should become the canonical ownership.
                </Text>
              </Stack>
            ) : null}
            <Radio.Group
              value={selectedMovieId}
              onChange={onChangeSelectedMovieId}
              label="Candidate movies"
            >
              <Stack gap="xs" mt="xs">
                {candidatesPayload.candidates.map((candidate) => (
                  <Radio
                    key={`candidate-${candidate.movie_id}`}
                    value={String(candidate.movie_id)}
                    label={`${candidate.title}${candidate.year ? ` (${candidate.year})` : ""} · ${candidate.confidence}`}
                    description={`${candidate.reasons.join("; ") || "No match reason"}${
                      candidate.mapping_conflict
                        ? ` · currently mapped to ${candidate.mapped_folder ?? "another folder"}`
                        : ""
                    }`}
                  />
                ))}
                {candidatesPayload.candidates.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    No candidates were found. You can still use Ignore for this folder.
                  </Text>
                ) : null}
              </Stack>
            </Radio.Group>
            <Radio.Group
              value={forceTakeover ? "force" : "safe"}
              onChange={(value) => onChangeForceTakeover(value === "force")}
              label="Ownership mode"
            >
              <Stack gap={4} mt="xs">
                <Radio value="safe" label="Safe (default): block if folder belongs to another movie" />
                <Radio
                  value="force"
                  label="Force takeover: override an active ownership conflict for the winner path"
                />
              </Stack>
            </Radio.Group>
            {selectedHasMappingConflict ? (
              <>
                <Radio.Group
                  value={winnerStrategy}
                  onChange={(value) =>
                    onChangeWinnerStrategy(value as UnmatchedMovieWinnerStrategy)
                  }
                  label="Choose winning folder"
                >
                  <Stack gap={4} mt="xs">
                    <Radio value="incoming" label="Use unmatched folder (incoming)" />
                    <Radio
                      value="existing"
                      label="Keep current mapped folder (existing)"
                    />
                  </Stack>
                </Radio.Group>
                <Checkbox
                  checked={quarantineLoser}
                  onChange={(event) => onChangeQuarantineLoser(event.currentTarget.checked)}
                  label="Quarantine loser folder into .deletedByLibrariarr"
                />
              </>
            ) : null}
          </>
        ) : null}
        {error ? <Text size="sm" c="red">{error}</Text> : null}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            loading={path !== null && busyImportPath === path}
            disabled={loading || !candidatesPayload || candidatesPayload.candidates.length === 0}
            onClick={onConfirm}
          >
            Map and Import
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
