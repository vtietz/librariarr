import { Group, Table, Text, ThemeIcon, Tooltip, ActionIcon } from "@mantine/core";
import { IconAlertTriangle, IconCheck, IconCopy, IconFolderOpen, IconX } from "@tabler/icons-react";
import { memo } from "react";

export type MappedDirectory = {
  shadow_root: string;
  virtual_path: string;
  real_path: string;
  target_exists: boolean;
};

type PathCellProps = {
  value: string;
  onCopy: (value: string) => Promise<void>;
  onOpen?: (value: string) => void;
};

const PathCell = memo(function PathCell({ value, onCopy, onOpen }: PathCellProps) {
  return (
    <Group gap="xs" wrap="nowrap" w="100%">
      <Text
        size="sm"
        title={value}
        style={{
          flex: 1,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
          minWidth: 0
        }}
      >
        {value}
      </Text>
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
      {onOpen ? (
        <Tooltip label="Open path">
          <ActionIcon size="sm" variant="light" aria-label="Open path" onClick={() => onOpen(value)}>
            <IconFolderOpen size={14} />
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
  onCopy: (value: string) => Promise<void>;
  onOpen: (value: string) => void;
};

const MappedRows = memo(function MappedRows({
  visibleDirectories,
  duplicatePrimaryPaths,
  excludedByDuplicate,
  duplicatePathSet,
  excludedPathSet,
  onCopy,
  onOpen
}: MappedRowsProps) {
  return (
    <>
      {visibleDirectories.map((mapped) => (
        <Table.Tr key={`${mapped.shadow_root}:${mapped.virtual_path}`}>
          <Table.Td style={{ width: "46%", minWidth: 0, paddingTop: 6, paddingBottom: 6 }}>
            <PathCell value={mapped.virtual_path} onCopy={onCopy} />
          </Table.Td>
          <Table.Td style={{ width: "46%", minWidth: 0, paddingTop: 6, paddingBottom: 6 }}>
            <PathCell value={mapped.real_path} onCopy={onCopy} onOpen={onOpen} />
          </Table.Td>
          <Table.Td style={{ width: "8%", minWidth: 0, paddingTop: 6, paddingBottom: 6 }}>
            <Group gap={6} wrap="nowrap" justify="flex-end">
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
            </Group>
          </Table.Td>
        </Table.Tr>
      ))}
    </>
  );
});

export default MappedRows;