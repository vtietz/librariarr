import { Stack, Text } from "@mantine/core";
import type { CSSProperties, ReactNode } from "react";
import WarningPathRow from "./WarningPathRow";

type StatusMessage = {
  color: string;
  message: string;
};

type DuplicateItem = {
  movie_ref: string;
  primary_path: string;
  duplicate_paths: string[];
  contains_excluded: boolean;
};

type Props = {
  item: DuplicateItem;
  onHover: (rowKey: string | null) => void;
  rowStyle: (rowKey: string) => CSSProperties;
  makeActions: (path: string) => ReactNode;
  statusByPath: Record<string, StatusMessage>;
};

export default function DuplicateWarningGroup({
  item,
  onHover,
  rowStyle,
  makeActions,
  statusByPath,
}: Props) {
  return (
    <Stack gap={0}>
      <Text size="xs" fw={500}>
        {item.movie_ref}
        {item.contains_excluded ? " (includes ignored path)" : ""}
      </Text>
      <WarningPathRow
        rowKey={`duplicate-${item.primary_path}`}
        label={`⚠ Primary candidate: ${item.primary_path}`}
        onHover={onHover}
        rowStyle={rowStyle}
        actions={makeActions(item.primary_path)}
        status={statusByPath[item.primary_path]}
      />
      {item.duplicate_paths.map((duplicatePath) => (
        <WarningPathRow
          key={`duplicate-path-${item.primary_path}-${duplicatePath}`}
          rowKey={`duplicate-${duplicatePath}`}
          label={`⚠ Alternative candidate: ${duplicatePath}`}
          onHover={onHover}
          rowStyle={rowStyle}
          actions={makeActions(duplicatePath)}
          status={statusByPath[duplicatePath]}
        />
      ))}
    </Stack>
  );
}
