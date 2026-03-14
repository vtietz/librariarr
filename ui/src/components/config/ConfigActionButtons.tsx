import { Button, Group } from "@mantine/core";
import { IconCheck } from "@tabler/icons-react";

type Props = {
  onValidate: () => void;
  onSave: () => void;
  onShowDiff?: () => void;
  onShowYamlPreview?: () => void;
  isValidating: boolean;
  isSaving: boolean;
  isLoadingDiff: boolean;
  validateSucceeded: boolean;
  saveSucceeded: boolean;
  diffButtonLabel?: string;
};

export default function ConfigActionButtons({
  onValidate,
  onSave,
  onShowDiff,
  onShowYamlPreview,
  isValidating,
  isSaving,
  isLoadingDiff,
  validateSucceeded,
  saveSucceeded,
  diffButtonLabel = "Show Diff"
}: Props) {
  return (
    <Group>
      <Button
        onClick={onValidate}
        loading={isValidating}
        leftSection={validateSucceeded ? <IconCheck size={16} /> : undefined}
      >
        {validateSucceeded ? "Validated" : "Validate Draft"}
      </Button>
      <Button
        variant="filled"
        color="green"
        onClick={onSave}
        loading={isSaving}
        leftSection={saveSucceeded ? <IconCheck size={16} /> : undefined}
      >
        {saveSucceeded ? "Saved" : "Save Config"}
      </Button>
      {onShowDiff ? (
        <Button variant="light" onClick={onShowDiff} loading={isLoadingDiff}>
          {diffButtonLabel}
        </Button>
      ) : null}
      {onShowYamlPreview ? (
        <Button variant="subtle" onClick={onShowYamlPreview}>
          Show YAML Preview
        </Button>
      ) : null}
    </Group>
  );
}
