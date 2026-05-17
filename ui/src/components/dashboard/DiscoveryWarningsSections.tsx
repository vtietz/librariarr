import { ActionIcon, Loader, Stack, Text, Tooltip } from "@mantine/core";
import { IconFolderOpen, IconTrash } from "@tabler/icons-react";
import type { CSSProperties, ReactNode } from "react";
import DuplicateWarningGroup from "./DuplicateWarningGroup";
import UnmatchedWarningsSection from "./UnmatchedWarningsSection";
import WarningPathRow from "./WarningPathRow";

type StatusMessage = { color: string; message: string };

type Props = {
  excludedCandidates: number;
  duplicateCandidates: number;
  orphanedManagedCandidates: number;
  unmatchedManagedCandidates: number;
  unmanagedShadowVideoFiles: number;
  excludedItems: Array<{ path: string; reason: string }>;
  duplicateItems: Array<{
    movie_ref: string;
    primary_path: string;
    duplicate_paths: string[];
    contains_excluded: boolean;
  }>;
  orphanedItems: Array<{ path: string; reason: string }>;
  unmatchedItems: Array<{ path: string; reason: string }>;
  unmanagedShadowItems: Array<{ path: string; reason: string }>;
  busyIgnorePath: string | null;
  busyOrphanPath: string | null;
  busyImportPath: string | null;
  importInFlightByPath: Record<string, boolean>;
  importErrorsByPath: Record<string, string>;
  importStatusByPath: Record<string, StatusMessage>;
  ignoreStatusByPath: Record<string, StatusMessage>;
  rowErrors: Record<string, string>;
  renderIgnoreAction: (path: string, label: string) => ReactNode;
  handleOpenFolder: (path: string) => Promise<void>;
  handleRecycleOrphan: (path: string) => Promise<void>;
  handleImportUnmatched: (path: string) => Promise<void>;
  setImportErrorDialogPath: (path: string) => void;
  setHoveredRowKey: (rowKey: string | null) => void;
  warningRowStyle: (rowKey: string) => CSSProperties;
};

export default function DiscoveryWarningsSections({
  excludedCandidates,
  duplicateCandidates,
  orphanedManagedCandidates,
  unmatchedManagedCandidates,
  unmanagedShadowVideoFiles,
  excludedItems,
  duplicateItems,
  orphanedItems,
  unmatchedItems,
  unmanagedShadowItems,
  busyIgnorePath,
  busyOrphanPath,
  busyImportPath,
  importInFlightByPath,
  importErrorsByPath,
  importStatusByPath,
  ignoreStatusByPath,
  rowErrors,
  renderIgnoreAction,
  handleOpenFolder,
  handleRecycleOrphan,
  handleImportUnmatched,
  setImportErrorDialogPath,
  setHoveredRowKey,
  warningRowStyle,
}: Props) {
  return (
    <Stack gap="sm" mt="xs">
      {excludedCandidates > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>Excluded Candidates ({excludedCandidates})</Text>
          {excludedItems.map((item) => (
            <WarningPathRow
              key={`excluded-${item.path}`}
              rowKey={`excluded-${item.path}`}
              label={`⚠ ${item.path}`}
              onHover={setHoveredRowKey}
              rowStyle={warningRowStyle}
              actions={
                <>
                  {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                  {renderIgnoreAction(item.path, "Keep ignored (add to paths.exclude_paths)")}
                </>
              }
              status={ignoreStatusByPath[item.path]}
            />
          ))}
        </Stack>
      )}
      {duplicateCandidates > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>Potential Duplicates ({duplicateCandidates})</Text>
          {duplicateItems.map((item) => (
            <DuplicateWarningGroup
              key={`duplicate-${item.primary_path}`}
              item={item}
              onHover={setHoveredRowKey}
              rowStyle={warningRowStyle}
              makeActions={(path) => (
                <>
                  {busyIgnorePath === path ? <Loader size="xs" /> : null}
                  {renderIgnoreAction(path, "Ignore this folder path")}
                </>
              )}
              statusByPath={ignoreStatusByPath}
            />
          ))}
        </Stack>
      )}
      {orphanedManagedCandidates > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            Orphaned Managed Folders (no video files) ({orphanedManagedCandidates})
          </Text>
          {orphanedItems.map((item) => (
            <WarningPathRow
              key={`orphaned-${item.path}`}
              rowKey={`orphaned-${item.path}`}
              label={`⚠ ${item.path}`}
              onHover={setHoveredRowKey}
              rowStyle={warningRowStyle}
              actions={
                <>
                  {busyOrphanPath === item.path ? <Loader size="xs" /> : null}
                  {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                  {renderIgnoreAction(item.path, "Ignore this folder path")}
                  <Tooltip label="Browse folder" withArrow>
                    <ActionIcon
                      size="sm"
                      variant="light"
                      onClick={() => void handleOpenFolder(item.path)}
                      disabled={busyOrphanPath === item.path}
                      aria-label="Browse orphaned folder"
                    >
                      <IconFolderOpen size={14} />
                    </ActionIcon>
                  </Tooltip>
                  <Tooltip label="Recycle orphaned folder" withArrow>
                    <ActionIcon
                      size="sm"
                      color="red"
                      variant="light"
                      onClick={() => void handleRecycleOrphan(item.path)}
                      disabled={busyOrphanPath === item.path}
                      aria-label="Recycle orphaned folder"
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </Tooltip>
                </>
              }
              status={ignoreStatusByPath[item.path]}
            />
          ))}
          {orphanedItems.map((item) => {
            const rowError = rowErrors[item.path];
            if (!rowError) {
              return null;
            }
            return (
              <Text key={`orphaned-error-${item.path}`} size="xs" c="red">
                {rowError}
              </Text>
            );
          })}
        </Stack>
      )}
      {unmanagedShadowVideoFiles > 0 && (
        <Stack gap={2}>
          <Text size="xs" fw={600}>
            Unmanaged Shadow Video Files ({unmanagedShadowVideoFiles})
          </Text>
          {unmanagedShadowItems.map((item) => (
            <WarningPathRow
              key={`shadow-unmanaged-${item.path}`}
              rowKey={`shadow-unmanaged-${item.path}`}
              label={`⚠ ${item.path}`}
              onHover={setHoveredRowKey}
              rowStyle={warningRowStyle}
              actions={
                <>
                  {busyIgnorePath === item.path ? <Loader size="xs" /> : null}
                  {renderIgnoreAction(item.path, "Ignore this file path")}
                </>
              }
              status={ignoreStatusByPath[item.path]}
            />
          ))}
        </Stack>
      )}
      <UnmatchedWarningsSection
        unmatchedManagedCandidates={unmatchedManagedCandidates}
        unmatchedItems={unmatchedItems}
        busyIgnorePath={busyIgnorePath}
        busyImportPath={busyImportPath}
        importInFlightByPath={importInFlightByPath}
        importErrorsByPath={importErrorsByPath}
        importStatusByPath={importStatusByPath}
        ignoreStatusByPath={ignoreStatusByPath}
        setImportErrorDialogPath={(path) => setImportErrorDialogPath(path)}
        handleImportUnmatched={handleImportUnmatched}
        renderIgnoreAction={renderIgnoreAction}
        onHover={setHoveredRowKey}
        rowStyle={warningRowStyle}
      />
    </Stack>
  );
}
