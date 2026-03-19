import {
  Alert,
  Badge,
  Group,
  Stack,
  Text,
  Title
} from "@mantine/core";
import { useEffect, useState } from "react";
import { IconCheck, IconX } from "@tabler/icons-react";
import { getFsRoots } from "../api/client";
import type { ConfigModel, Issue } from "../types/config";
import ConfigActionButtons from "./config/ConfigActionButtons";
import MiscSections from "./config/MiscSections";
import ConfigViewerModal from "./config/ConfigViewerModal";
import RadarrSection from "./config/RadarrSection";
import SonarrSection from "./config/SonarrSection";
import PathsSection from "./config/PathsSection";
import DirectoryPickerModal from "./DirectoryPickerModal";

type Props = {
  draft: ConfigModel;
  hasUnsavedChanges: boolean;
  issues: Issue[];
  yamlPreview: string;
  onValidate: () => Promise<void>;
  onSave: () => Promise<void>;
  onLoadDiff: () => Promise<void>;
  diffText: string;
  onChange: (next: ConfigModel) => void;
};

export default function ConfigEditor({
  draft,
  hasUnsavedChanges,
  issues,
  yamlPreview,
  onValidate,
  onSave,
  onLoadDiff,
  diffText,
  onChange
}: Props) {
  const [pickerRoots, setPickerRoots] = useState<string[]>([]);
  const [pickerTarget, setPickerTarget] = useState<{
    index: number;
    key: "nested_root" | "shadow_root";
  } | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingDiff, setIsLoadingDiff] = useState(false);
  const [validateSucceeded, setValidateSucceeded] = useState(false);
  const [saveSucceeded, setSaveSucceeded] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [viewerMode, setViewerMode] = useState<"yaml" | "diff" | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        setPickerRoots(await getFsRoots());
      } catch {
        setPickerRoots([]);
      }
    })();
  }, []);

  const setSectionField = <T extends keyof ConfigModel>(
    section: T,
    field: keyof ConfigModel[T],
    value: unknown
  ) => {
    onChange({
      ...draft,
      [section]: {
        ...draft[section],
        [field]: value
      }
    });
  };

  const normalizeCleanupAction = (value: string | null): "none" | "unmonitor" | "delete" => {
    if (value === "delete" || value === "unmonitor" || value === "none") {
      return value;
    }
    return "none";
  };

  const setCleanupAction = (value: string | null) => {
    const nextAction = normalizeCleanupAction(value);

    onChange({
      ...draft,
      cleanup: {
        ...draft.cleanup,
        sonarr_action_on_missing: nextAction
      }
    });
  };

  const setRootMapping = (index: number, key: "nested_root" | "shadow_root", value: string) => {
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        series_root_mappings: draft.paths.series_root_mappings.map((mapping, mappingIndex) => {
          if (mappingIndex !== index) {
            return mapping;
          }
          return { ...mapping, [key]: value };
        })
      }
    });
  };

  const removeRootMapping = (index: number) => {
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        series_root_mappings: draft.paths.series_root_mappings.filter(
          (_, mappingIndex) => mappingIndex !== index
        )
      }
    });
  };

  const addRootMapping = () => {
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        series_root_mappings: [
          ...draft.paths.series_root_mappings,
          { nested_root: "", shadow_root: "" }
        ]
      }
    });
  };

  const pickerInitialPath =
    pickerTarget == null
      ? ""
      : draft.paths.series_root_mappings[pickerTarget.index]?.[pickerTarget.key] ?? "";

  const parseActionError = (error: unknown): string => {
    if (typeof error !== "object" || error === null) {
      return "Request failed. Please try again.";
    }

    const maybeResponse = (error as { response?: { data?: unknown } }).response;
    const detail =
      maybeResponse &&
      typeof maybeResponse.data === "object" &&
      maybeResponse.data !== null &&
      "detail" in maybeResponse.data
        ? (maybeResponse.data as { detail?: unknown }).detail
        : undefined;

    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }

    const message = "message" in (error as Record<string, unknown>) ? (error as { message?: unknown }).message : undefined;
    if (typeof message === "string" && message.trim().length > 0) {
      return message;
    }

    return "Request failed. Please try again.";
  };

  const handleValidate = async () => {
    setActionError(null);
    setValidateSucceeded(false);
    setIsValidating(true);
    try {
      await onValidate();
      setValidateSucceeded(true);
      window.setTimeout(() => setValidateSucceeded(false), 1800);
    } catch (error: unknown) {
      setActionError(parseActionError(error));
    } finally {
      setIsValidating(false);
    }
  };

  const handleSave = async () => {
    setActionError(null);
    setSaveSucceeded(false);
    setIsSaving(true);
    try {
      await onSave();
      setSaveSucceeded(true);
      window.setTimeout(() => setSaveSucceeded(false), 1800);
    } catch (error: unknown) {
      setActionError(parseActionError(error));
    } finally {
      setIsSaving(false);
    }
  };

  const handleOpenDiff = async () => {
    setActionError(null);
    setIsLoadingDiff(true);
    try {
      await onLoadDiff();
      setViewerMode("diff");
    } catch (error: unknown) {
      setActionError(parseActionError(error));
    } finally {
      setIsLoadingDiff(false);
    }
  };

  const handleOpenYamlPreview = () => {
    setActionError(null);
    setViewerMode("yaml");
  };

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Config Editor</Title>
        <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
          {hasUnsavedChanges ? "Unsaved changes" : "No pending changes"}
        </Badge>
      </Group>

      <ConfigActionButtons
        onValidate={() => void handleValidate()}
        onSave={() => void handleSave()}
        onShowDiff={() => void handleOpenDiff()}
        onShowYamlPreview={handleOpenYamlPreview}
        isValidating={isValidating}
        isSaving={isSaving}
        isLoadingDiff={isLoadingDiff}
        validateSucceeded={validateSucceeded}
        saveSucceeded={saveSucceeded}
      />

      {actionError && (
        <Alert color="red" title="Action failed" icon={<IconX size={16} />}>
          <Text size="sm">{actionError}</Text>
        </Alert>
      )}

      {(validateSucceeded || saveSucceeded) && !actionError && (
        <Alert color="green" title="Success" icon={<IconCheck size={16} />}>
          <Text size="sm">
            {saveSucceeded
              ? "Configuration saved successfully."
              : "Draft validation completed successfully."}
          </Text>
        </Alert>
      )}

      {viewerMode ? (
        <ConfigViewerModal
          opened={viewerMode !== null}
          mode={viewerMode}
          yamlPreview={yamlPreview}
          diffText={diffText}
          onClose={() => setViewerMode(null)}
          onValidate={() => void handleValidate()}
          onSave={() => void handleSave()}
          onRefreshDiff={() => void handleOpenDiff()}
          isValidating={isValidating}
          isSaving={isSaving}
          isLoadingDiff={isLoadingDiff}
          validateSucceeded={validateSucceeded}
          saveSucceeded={saveSucceeded}
        />
      ) : null}

      {issues.length > 0 && (
        <Alert color="yellow" title="Validation Issues">
          <Stack gap="xs">
            {issues.map((issue, index) => (
              <Text key={`issue-${index}`} size="sm">
                [{issue.severity}] {issue.message}
              </Text>
            ))}
          </Stack>
        </Alert>
      )}

      <PathsSection
        rootMappings={draft.paths.series_root_mappings}
        excludePaths={draft.paths.exclude_paths ?? []}
        onAddMapping={addRootMapping}
        onRemoveMapping={removeRootMapping}
        onSetMapping={setRootMapping}
        onOpenPicker={(index, key) => setPickerTarget({ index, key })}
        onExcludePathsChange={(excludePaths) =>
          onChange({
            ...draft,
            paths: {
              ...draft.paths,
              exclude_paths: excludePaths
            }
          })
        }
      />

      <RadarrSection
        value={draft.radarr}
        onChange={(nextRadarr) => onChange({ ...draft, radarr: nextRadarr })}
      />

      <SonarrSection
        value={draft.sonarr}
        onChange={(nextSonarr) => onChange({ ...draft, sonarr: nextSonarr })}
      />

      <MiscSections
        draft={draft}
        onSetSectionField={setSectionField}
        onSetCleanupAction={setCleanupAction}
      />

      <DirectoryPickerModal
        opened={pickerTarget !== null}
        title="Select directory for mapping"
        roots={pickerRoots}
        initialPath={pickerInitialPath}
        onClose={() => setPickerTarget(null)}
        onSelect={(path) => {
          if (!pickerTarget) {
            return;
          }
          setRootMapping(pickerTarget.index, pickerTarget.key, path);
          setPickerTarget(null);
        }}
      />
    </Stack>
  );
}
