import { Box, Group, Modal, ScrollArea, Stack, Text } from "@mantine/core";
import ConfigActionButtons from "./ConfigActionButtons";

type Props = {
  opened: boolean;
  mode: "yaml" | "diff";
  yamlPreview: string;
  diffText: string;
  onClose: () => void;
  onValidate: () => void;
  onSave: () => void;
  onRefreshDiff: () => void;
  isValidating: boolean;
  isSaving: boolean;
  isLoadingDiff: boolean;
  validateSucceeded: boolean;
  saveSucceeded: boolean;
};

function renderDiffLine(line: string, index: number) {
  let color: string | undefined;
  let background: string | undefined;

  if (line.startsWith("+")) {
    color = "green.3";
    background = "var(--mantine-color-green-light)";
  } else if (line.startsWith("-")) {
    color = "red.3";
    background = "var(--mantine-color-red-light)";
  } else if (line.startsWith("@@") || line.startsWith("diff ") || line.startsWith("index ")) {
    color = "blue.3";
    background = "var(--mantine-color-blue-light)";
  } else if (line.startsWith("---") || line.startsWith("+++")) {
    color = "cyan.3";
    background = "var(--mantine-color-cyan-light)";
  }

  return (
    <Text
      key={`diff-line-${index}`}
      size="sm"
      ff="monospace"
      px="xs"
      py={2}
      c={color}
      style={{ backgroundColor: background }}
    >
      {line || " "}
    </Text>
  );
}

function renderYamlLine(line: string, index: number) {
  return (
    <Group key={`yaml-line-${index}`} gap="xs" wrap="nowrap" align="flex-start">
      <Text c="dimmed" size="sm" ff="monospace" ta="right" w={56}>
        {index + 1}
      </Text>
      <Text size="sm" ff="monospace" style={{ whiteSpace: "pre" }}>
        {line || " "}
      </Text>
    </Group>
  );
}

export default function ConfigViewerModal({
  opened,
  mode,
  yamlPreview,
  diffText,
  onClose,
  onValidate,
  onSave,
  onRefreshDiff,
  isValidating,
  isSaving,
  isLoadingDiff,
  validateSucceeded,
  saveSucceeded
}: Props) {
  return (
    <Modal opened={opened} onClose={onClose} fullScreen title={mode === "diff" ? "Config Diff" : "YAML Preview"}>
      <Stack h="100%" gap="sm">
        <ConfigActionButtons
          onValidate={onValidate}
          onSave={onSave}
          onShowDiff={mode === "diff" ? onRefreshDiff : undefined}
          isValidating={isValidating}
          isSaving={isSaving}
          isLoadingDiff={isLoadingDiff}
          validateSucceeded={validateSucceeded}
          saveSucceeded={saveSucceeded}
          diffButtonLabel="Refresh Diff"
        />

        <ScrollArea h="calc(100vh - 180px)" offsetScrollbars>
          {mode === "diff" ? (
            diffText.trim().length > 0 ? (
              <Box>{diffText.split("\n").map((line, index) => renderDiffLine(line, index))}</Box>
            ) : (
              <Text c="dimmed" size="sm">
                No diff available.
              </Text>
            )
          ) : yamlPreview.trim().length > 0 ? (
            <Box>{yamlPreview.split("\n").map((line, index) => renderYamlLine(line, index))}</Box>
          ) : (
            <Text c="dimmed" size="sm">
              YAML preview is empty. Validate the draft to regenerate it.
            </Text>
          )}
        </ScrollArea>
      </Stack>
    </Modal>
  );
}
