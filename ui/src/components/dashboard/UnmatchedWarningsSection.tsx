import {
  ActionIcon,
  Loader,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconAlertCircle, IconUpload } from "@tabler/icons-react";
import type { CSSProperties, ReactNode } from "react";
import WarningPathRow from "./WarningPathRow";

type StatusMessage = {
  color: string;
  message: string;
};

type Props = {
  unmatchedManagedCandidates: number;
  unmatchedItems: Array<{ path: string; reason: string }>;
  busyIgnorePath: string | null;
  busyImportPath: string | null;
  importInFlightByPath: Record<string, boolean>;
  importErrorsByPath: Record<string, string>;
  importStatusByPath: Record<string, StatusMessage>;
  ignoreStatusByPath: Record<string, StatusMessage>;
  setImportErrorDialogPath: (path: string) => void;
  handleImportUnmatched: (path: string) => Promise<void>;
  renderIgnoreAction: (path: string, label: string) => ReactNode;
  onHover: (rowKey: string | null) => void;
  rowStyle: (rowKey: string) => CSSProperties;
};

export default function UnmatchedWarningsSection({
  unmatchedManagedCandidates,
  unmatchedItems,
  busyIgnorePath,
  busyImportPath,
  importInFlightByPath,
  importErrorsByPath,
  importStatusByPath,
  ignoreStatusByPath,
  setImportErrorDialogPath,
  handleImportUnmatched,
  renderIgnoreAction,
  onHover,
  rowStyle,
}: Props) {
  if (unmatchedManagedCandidates <= 0) {
    return null;
  }

  return (
    <Stack gap={2}>
      <Text size="xs" fw={600}>
        Unmatched Managed Folders ({unmatchedManagedCandidates})
      </Text>
      <Text size="xs" c="dimmed">
        Usually this means the folder is not imported in Radarr yet.
      </Text>
      {unmatchedItems.map((item) => (
        <Stack key={`unmatched-${item.path}`} gap={0}>
          <WarningPathRow
            rowKey={`unmatched-${item.path}`}
            label={`⚠ ${item.path}`}
            onHover={onHover}
            rowStyle={rowStyle}
            actions={
              <>
                {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                {renderIgnoreAction(item.path, "Ignore this folder path")}
                {busyImportPath === item.path || importInFlightByPath[item.path] ? (
                  <Loader size="xs" />
                ) : null}
                {importErrorsByPath[item.path] ? (
                  <Tooltip
                    label="Import failed. Click for details and retry."
                    withArrow
                  >
                    <ActionIcon
                      size="sm"
                      color="red"
                      variant="light"
                      onClick={() => setImportErrorDialogPath(item.path)}
                      disabled={busyImportPath === item.path}
                      aria-label="Show import error details"
                    >
                      <IconAlertCircle size={14} />
                    </ActionIcon>
                  </Tooltip>
                ) : (
                  <Tooltip label="Trigger import to Radarr" withArrow>
                    <ActionIcon
                      size="sm"
                      color="blue"
                      variant="light"
                      onClick={() => void handleImportUnmatched(item.path)}
                      disabled={busyImportPath === item.path}
                      aria-label="Import unmatched folder"
                    >
                      <IconUpload size={14} />
                    </ActionIcon>
                  </Tooltip>
                )}
              </>
            }
          />
          {importStatusByPath[item.path] ? (
            <Text size="xs" c={importStatusByPath[item.path].color}>
              {importStatusByPath[item.path].message}
            </Text>
          ) : null}
          {ignoreStatusByPath[item.path] ? (
            <Text size="xs" c={ignoreStatusByPath[item.path].color}>
              {ignoreStatusByPath[item.path].message}
            </Text>
          ) : null}
        </Stack>
      ))}
    </Stack>
  );
}
