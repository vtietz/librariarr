import {
  Button,
  Checkbox,
  Group,
  Loader,
  Modal,
  Radio,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import type {
  UnmatchedFolderComparisonInfo,
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
  const incomingFolderInfo = candidatesPayload?.incoming_folder_info ?? null;
  const mappedFolderInfo = selectedCandidate?.mapped_folder_info ?? null;

  const formatTimestamp = (value: number | null | undefined) => {
    if (typeof value !== "number") {
      return "-";
    }
    return new Date(value * 1000).toLocaleString();
  };

  const formatBytes = (value: number) => {
    if (value <= 0) {
      return "0 B";
    }
    const units = ["B", "KB", "MB", "GB", "TB"];
    const unitIndex = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
    const scaled = value / 1024 ** unitIndex;
    return `${scaled.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  };

  const folderFileSummary = (info: UnmatchedFolderComparisonInfo | null) => {
    if (!info) {
      return "-";
    }
    if (info.sample_video_files.length === 0) {
      return "No video files found";
    }
    return info.sample_video_files.join(", ");
  };

  return (
    <Modal
      opened={opened}
      onClose={onCancel}
      title="Resolve Unmatched Folder"
      centered
      size="80rem"
    >
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
                <Radio
                  value="safe"
                  label="Safe (default): block only when the selected winner folder is actively owned by another movie"
                />
                <Radio
                  value="force"
                  label="Force takeover: override that active winner-folder ownership conflict"
                />
              </Stack>
            </Radio.Group>
            <Text size="xs" c="dimmed">
              Force takeover is usually only needed when your chosen winner folder is already mapped
              to another active movie. If the conflict owner is stale/invalid, safe mode can still
              reassign automatically.
            </Text>
            {selectedHasMappingConflict ? (
              <>
                {incomingFolderInfo && mappedFolderInfo ? (
                  <Stack gap={4}>
                    <Text size="sm" fw={500}>
                      Folder comparison
                    </Text>
                    <Table withTableBorder withColumnBorders striped highlightOnHover>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>Field</Table.Th>
                          <Table.Th>Incoming folder</Table.Th>
                          <Table.Th>Existing mapped folder</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        <Table.Tr>
                          <Table.Td>Path</Table.Td>
                          <Table.Td>{incomingFolderInfo.path}</Table.Td>
                          <Table.Td>{mappedFolderInfo.path}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Video files</Table.Td>
                          <Table.Td>{incomingFolderInfo.video_count}</Table.Td>
                          <Table.Td>{mappedFolderInfo.video_count}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Example filenames</Table.Td>
                          <Table.Td>{folderFileSummary(incomingFolderInfo)}</Table.Td>
                          <Table.Td>{folderFileSummary(mappedFolderInfo)}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Latest video file</Table.Td>
                          <Table.Td>{incomingFolderInfo.latest_video_file ?? "-"}</Table.Td>
                          <Table.Td>{mappedFolderInfo.latest_video_file ?? "-"}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Latest video modified</Table.Td>
                          <Table.Td>{formatTimestamp(incomingFolderInfo.latest_video_mtime)}</Table.Td>
                          <Table.Td>{formatTimestamp(mappedFolderInfo.latest_video_mtime)}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Folder created</Table.Td>
                          <Table.Td>{formatTimestamp(incomingFolderInfo.folder_created_at)}</Table.Td>
                          <Table.Td>{formatTimestamp(mappedFolderInfo.folder_created_at)}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Folder changed</Table.Td>
                          <Table.Td>{formatTimestamp(incomingFolderInfo.folder_changed_at)}</Table.Td>
                          <Table.Td>{formatTimestamp(mappedFolderInfo.folder_changed_at)}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Folder modified</Table.Td>
                          <Table.Td>{formatTimestamp(incomingFolderInfo.folder_modified_at)}</Table.Td>
                          <Table.Td>{formatTimestamp(mappedFolderInfo.folder_modified_at)}</Table.Td>
                        </Table.Tr>
                        <Table.Tr>
                          <Table.Td>Total video size</Table.Td>
                          <Table.Td>{formatBytes(incomingFolderInfo.video_size_bytes)}</Table.Td>
                          <Table.Td>{formatBytes(mappedFolderInfo.video_size_bytes)}</Table.Td>
                        </Table.Tr>
                      </Table.Tbody>
                    </Table>
                    <Text size="xs" c="dimmed">
                      Folder created is only shown when the filesystem exposes a birth timestamp.
                    </Text>
                  </Stack>
                ) : null}
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
