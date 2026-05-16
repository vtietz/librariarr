import { Group, Stack, Text } from "@mantine/core";
import type { CSSProperties, ReactNode } from "react";

type StatusMessage = {
  color: string;
  message: string;
};

type Props = {
  rowKey: string;
  label: string;
  onHover: (rowKey: string | null) => void;
  rowStyle: (rowKey: string) => CSSProperties;
  actions?: ReactNode;
  status?: StatusMessage;
};

export default function WarningPathRow({
  rowKey,
  label,
  onHover,
  rowStyle,
  actions,
  status,
}: Props) {
  return (
    <Stack gap={0}>
      <Group
        gap="xs"
        wrap="nowrap"
        onMouseEnter={() => onHover(rowKey)}
        onMouseLeave={() => onHover(null)}
        style={rowStyle(rowKey)}
      >
        <Text size="xs" c="dimmed" style={{ flex: 1, minWidth: 0 }}>
          {label}
        </Text>
        {actions}
      </Group>
      {status ? (
        <Text size="xs" c={status.color}>
          {status.message}
        </Text>
      ) : null}
    </Stack>
  );
}
