import { Group, Table, Text, ThemeIcon, Tooltip, ActionIcon, Transition } from "@mantine/core";
import {
  IconAlertTriangle,
  IconArrowsShuffle,
  IconCheck,
  IconCopy,
  IconRefresh,
  IconSearch,
  IconX
} from "@tabler/icons-react";
import { memo } from "react";

export type MappedDirectory = {
  shadow_root: string;
  virtual_path: string;
  real_path: string;
  target_exists: boolean;
  arr_state?: string;
  arr_movie_id?: number | null;
  arr_title?: string | null;
  arr_monitored?: boolean | null;
};

type PathCellProps = {
  value: string;
  onCopy: (value: string) => Promise<void>;
  onOpen?: (value: string) => void;
};

const PathCell = memo(function PathCell({ value, onCopy, onOpen }: PathCellProps) {
  const hasValue = value.trim().length > 0;
  const displayValue = hasValue ? value : "—";
  return (
    <Group gap="xs" wrap="nowrap" w="100%">
      <Text
        size="sm"
        title={hasValue ? value : undefined}
        style={{
          flex: 1,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          minWidth: 0
        }}
      >
        {displayValue}
      </Text>
      {hasValue ? (
        <Tooltip label="Copy path">
          <ActionIcon
            size="sm"
            variant="light"
            aria-label="Copy path"
            onClick={() => void onCopy(value)}
          >
            <IconCopy size={14} />
          </ActionIcon>
        </Tooltip>
      ) : null}
      {onOpen && hasValue ? (
        <Tooltip label="Inspect path">
          <ActionIcon size="sm" variant="light" aria-label="Inspect path" onClick={() => onOpen(value)}>
            <IconSearch size={14} />
          </ActionIcon>
        </Tooltip>
      ) : null}
    </Group>
  );
});

type MappedRowsProps = {
  visibleDirectories: MappedDirectory[];
  duplicatePrimaryPaths: Set<string>;
  excludedByDuplicate: Map<string, number>;
  duplicatePathSet: Set<string>;
  excludedPathSet: Set<string>;
  refreshingMovieId: number | null;
  reconcilingPath: string | null;
  recentlyReconciledPath: string | null;
  onCopy: (value: string) => Promise<void>;
  onOpen: (value: string) => void;
  onRefreshRadarr: (movieId: number) => Promise<void>;
  onReconcilePath: (path: string) => Promise<void>;
};

function arrStateBadge(state: string | undefined): { label: string; color: string } {
  switch (state) {
    case "ok":
      return { label: "Arr ok", color: "green" };
    case "missing_on_disk":
      return { label: "Missing target", color: "red" };
    case "missing_virtual_path":
      return { label: "Missing virtual", color: "red" };
    case "title_path_mismatch":
      return { label: "Path mismatch", color: "yellow" };
    case "missing_in_arr":
      return { label: "Not in Arr", color: "orange" };
    case "arr_unreachable":
      return { label: "Arr offline", color: "gray" };
    default:
      return { label: "N/A", color: "gray" };
  }
}

const MappedRows = memo(function MappedRows({
  visibleDirectories,
  duplicatePrimaryPaths,
  excludedByDuplicate,
  duplicatePathSet,
  excludedPathSet,
  refreshingMovieId,
  reconcilingPath,
  recentlyReconciledPath,
  onCopy,
  onOpen,
  onRefreshRadarr,
  onReconcilePath
}: MappedRowsProps) {
  return (
    <>
      {visibleDirectories.map((mapped) => (
        <Table.Tr key={`${mapped.shadow_root}:${mapped.virtual_path}`}>
          <Table.Td style={{ width: "42%", minWidth: 0, paddingTop: 6, paddingBottom: 6 }}>
            <PathCell value={mapped.virtual_path} onCopy={onCopy} />
          </Table.Td>
          <Table.Td style={{ width: "42%", minWidth: 0, paddingTop: 6, paddingBottom: 6 }}>
            <PathCell value={mapped.real_path} onCopy={onCopy} onOpen={onOpen} />
          </Table.Td>
          <Table.Td style={{ width: "16%", minWidth: 0, paddingTop: 6, paddingBottom: 6 }}>
            <Group gap={6} wrap="nowrap" justify="flex-end">
              <Tooltip label={mapped.arr_title || "Arr path state"}>
                <ThemeIcon
                  size="sm"
                  radius="xl"
                  variant="light"
                  color={arrStateBadge(mapped.arr_state).color}
                >
                  <Text size="10px" fw={700}>{arrStateBadge(mapped.arr_state).label[0]}</Text>
                </ThemeIcon>
              </Tooltip>
              <Tooltip label={mapped.target_exists ? "Target exists" : "Missing target"}>
                <ThemeIcon
                  size="sm"
                  radius="xl"
                  variant="light"
                  color={mapped.target_exists ? "green" : "red"}
                >
                  {mapped.target_exists ? <IconCheck size={14} /> : <IconX size={14} />}
                </ThemeIcon>
              </Tooltip>
              {duplicatePathSet.has(mapped.real_path) && (
                <Tooltip
                  label={
                    duplicatePrimaryPaths.has(mapped.real_path)
                      ? "Duplicate warning (primary path)"
                      : "Duplicate warning (alternative path)"
                  }
                >
                  <ThemeIcon size="sm" radius="xl" variant="light" color="yellow">
                    <IconAlertTriangle size={13} />
                  </ThemeIcon>
                </Tooltip>
              )}
              {excludedPathSet.has(mapped.real_path) && (
                <Tooltip label="Excluded by paths.exclude_paths">
                  <ThemeIcon size="sm" radius="xl" variant="light" color="orange">
                    <IconAlertTriangle size={13} />
                  </ThemeIcon>
                </Tooltip>
              )}
              {(excludedByDuplicate.get(mapped.real_path) ?? 0) > 0 && (
                <Tooltip
                  label={`Excluded alternative paths: ${excludedByDuplicate.get(mapped.real_path)}`}
                >
                  <ThemeIcon size="sm" radius="xl" variant="light" color="orange">
                    E
                  </ThemeIcon>
                </Tooltip>
              )}
              {typeof mapped.arr_movie_id === "number" && (
                <Tooltip label="Refresh in Radarr">
                  <ActionIcon
                    size="sm"
                    variant="light"
                    aria-label="Refresh in Radarr"
                    onClick={() => void onRefreshRadarr(mapped.arr_movie_id as number)}
                    loading={refreshingMovieId === mapped.arr_movie_id}
                  >
                    <IconRefresh size={14} />
                  </ActionIcon>
                </Tooltip>
              )}
              {mapped.real_path.trim().length > 0 && (
                <Tooltip label="Reconcile this path">
                  <ActionIcon
                    size="sm"
                    variant="light"
                    aria-label="Reconcile this path"
                    onClick={() => void onReconcilePath(mapped.real_path)}
                    loading={reconcilingPath === mapped.real_path}
                    disabled={reconcilingPath !== null && reconcilingPath !== mapped.real_path}
                  >
                    <IconArrowsShuffle size={14} />
                  </ActionIcon>
                </Tooltip>
              )}
              <Transition
                mounted={mapped.real_path === recentlyReconciledPath}
                transition="fade"
                duration={220}
                timingFunction="ease"
              >
                {(styles) => (
                  <Tooltip label="Reconcile completed">
                    <ThemeIcon
                      size="sm"
                      radius="xl"
                      variant="light"
                      color="green"
                      style={styles}
                    >
                      <IconCheck size={13} />
                    </ThemeIcon>
                  </Tooltip>
                )}
              </Transition>
            </Group>
          </Table.Td>
        </Table.Tr>
      ))}
    </>
  );
});

export default MappedRows;