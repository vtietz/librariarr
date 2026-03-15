import { Badge, Group, Table, Text, ThemeIcon, Tooltip, ActionIcon } from "@mantine/core";
import { IconCheck, IconCopy, IconFolderOpen, IconX } from "@tabler/icons-react";
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
  onOpen: (value: string) => void;
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
      <Tooltip label="Open path">
        <ActionIcon size="sm" variant="light" aria-label="Open path" onClick={() => onOpen(value)}>
          <IconFolderOpen size={14} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
});

type MappedRowsProps = {
  visibleDirectories: MappedDirectory[];
  duplicatePrimaryPaths: Set<string>;
  excludedByDuplicate: Map<string, number>;
  onCopy: (value: string) => Promise<void>;
  onOpen: (value: string) => void;
};

const MappedRows = memo(function MappedRows({
  visibleDirectories,
  duplicatePrimaryPaths,
  excludedByDuplicate,
  onCopy,
  onOpen
}: MappedRowsProps) {
  return (
    <>
      {visibleDirectories.map((mapped) => (
        <Table.Tr key={`${mapped.shadow_root}:${mapped.virtual_path}`}>
          <Table.Td style={{ width: "44%", minWidth: 0 }}>
            <PathCell value={mapped.virtual_path} onCopy={onCopy} onOpen={onOpen} />
          </Table.Td>
          <Table.Td style={{ width: "44%", minWidth: 0 }}>
            <PathCell value={mapped.real_path} onCopy={onCopy} onOpen={onOpen} />
          </Table.Td>
          <Table.Td style={{ width: "12%", minWidth: 0 }}>
            <Group gap={6}>
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
              {duplicatePrimaryPaths.has(mapped.real_path) && (
                <Badge color="yellow">⚠ duplicate candidate</Badge>
              )}
              {(excludedByDuplicate.get(mapped.real_path) ?? 0) > 0 && (
                <Badge color="orange">
                  excluded alt paths: {excludedByDuplicate.get(mapped.real_path)}
                </Badge>
              )}
            </Group>
          </Table.Td>
        </Table.Tr>
      ))}
    </>
  );
});

export default MappedRows;