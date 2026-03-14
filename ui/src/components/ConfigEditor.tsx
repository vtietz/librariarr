import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  TagsInput,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { useEffect, useState } from "react";
import { getFsRoots } from "../api/client";
import type { ConfigModel, Issue } from "../types/config";
import RadarrSection from "./config/RadarrSection";
import SonarrSection from "./config/SonarrSection";
import HelpLabel from "./config/HelpLabel";
import PathsSection from "./config/PathsSection";
import DirectoryPickerModal from "./DirectoryPickerModal";

const VIDEO_EXTENSION_SUGGESTIONS = [
  "mkv",
  "mp4",
  "avi",
  "m2ts",
  "mov",
  "wmv",
  "ts",
  "flv",
  "webm",
  "m4v",
  "mpg",
  "mpeg"
];

function normalizeVideoExtensions(values: string[]): string[] {
  const normalized = values
    .map((value) => String(value).trim().toLowerCase())
    .map((value) => value.replace(/^\.+/, ""))
    .filter((value) => value.length > 0)
    .filter((value) => !value.includes(" "));
  return Array.from(new Set(normalized));
}

type Props = {
  draft: ConfigModel;
  hasUnsavedChanges: boolean;
  issues: Issue[];
  yamlPreview: string;
  showYamlPreview: boolean;
  onToggleYamlPreview: () => void;
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
  showYamlPreview,
  onToggleYamlPreview,
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

  const setCleanupAction = (target: "radarr" | "sonarr", value: string | null) => {
    const nextAction = normalizeCleanupAction(value);
    const nextRadarrAction =
      target === "radarr" ? nextAction : normalizeCleanupAction(draft.cleanup.radarr_action_on_missing);
    const nextSonarrAction =
      target === "sonarr" ? nextAction : normalizeCleanupAction(draft.cleanup.sonarr_action_on_missing);

    onChange({
      ...draft,
      cleanup: {
        ...draft.cleanup,
        radarr_action_on_missing: nextRadarrAction,
        sonarr_action_on_missing: nextSonarrAction
      }
    });
  };

  const setRootMapping = (index: number, key: "nested_root" | "shadow_root", value: string) => {
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        root_mappings: draft.paths.root_mappings.map((mapping, mappingIndex) => {
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
        root_mappings: draft.paths.root_mappings.filter((_, mappingIndex) => mappingIndex !== index)
      }
    });
  };

  const addRootMapping = () => {
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        root_mappings: [...draft.paths.root_mappings, { nested_root: "", shadow_root: "" }]
      }
    });
  };

  const pickerInitialPath =
    pickerTarget == null ? "" : draft.paths.root_mappings[pickerTarget.index]?.[pickerTarget.key] ?? "";

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={3}>Config Editor</Title>
        <Badge color={hasUnsavedChanges ? "yellow" : "green"}>
          {hasUnsavedChanges ? "Unsaved changes" : "No pending changes"}
        </Badge>
      </Group>

      <Group>
        <Button onClick={onValidate}>Validate Draft</Button>
        <Button variant="filled" color="green" onClick={onSave}>
          Save Config
        </Button>
        <Button variant="light" onClick={onLoadDiff}>
          Show Diff
        </Button>
        <Button variant="subtle" onClick={onToggleYamlPreview}>
          {showYamlPreview ? "Hide YAML Preview" : "Show YAML Preview"}
        </Button>
      </Group>

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
        rootMappings={draft.paths.root_mappings}
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

      <Card withBorder>
        <Title order={4}>Ingest</Title>
        <Stack mt="sm">
          <Switch
            label={
              <HelpLabel
                label="Enabled"
                help="Moves real folders from shadow roots back to nested roots when safe."
              />
            }
            checked={draft.ingest.enabled}
            onChange={(event) => setSectionField("ingest", "enabled", event.currentTarget.checked)}
          />
          <Group grow align="flex-end">
            <NumberInput
              label={
                <HelpLabel
                  label="Minimum Age Seconds"
                  help="Minimum stable age before ingest is allowed to move a folder."
                />
              }
              value={draft.ingest.min_age_seconds}
              min={0}
              onChange={(value) => setSectionField("ingest", "min_age_seconds", Number(value) || 0)}
            />
            <Select
              label={
                <HelpLabel
                  label="Collision Policy"
                  help="How ingest handles name conflicts: qualify appends a suffix, skip leaves the source untouched."
                />
              }
              data={["qualify", "skip"]}
              value={draft.ingest.collision_policy}
              onChange={(value) => setSectionField("ingest", "collision_policy", value ?? "qualify")}
            />
            <TextInput
              label={
                <HelpLabel
                  label="Quarantine Root"
                  help="Optional folder where failed ingest moves can be placed for recovery."
                />
              }
              value={draft.ingest.quarantine_root}
              onChange={(event) => setSectionField("ingest", "quarantine_root", event.currentTarget.value)}
            />
          </Group>
        </Stack>
      </Card>

      <Card withBorder>
        <Title order={4}>Cleanup</Title>
        <Stack mt="sm">
          <Group>
            <Checkbox
              label={
                <HelpLabel
                  label="Remove orphaned links"
                  help="Deletes stale links in shadow roots when their source folder no longer exists."
                />
              }
              checked={draft.cleanup.remove_orphaned_links}
              onChange={(event) =>
                setSectionField("cleanup", "remove_orphaned_links", event.currentTarget.checked)
              }
            />
          </Group>
          <Group grow align="flex-end">
            <Select
              label={
                <HelpLabel
                  label="Radarr Action On Missing"
                  help="Action to apply in Radarr when a source folder stays missing after grace period."
                />
              }
              data={["none", "unmonitor", "delete"]}
              value={draft.cleanup.radarr_action_on_missing}
              onChange={(value) => setCleanupAction("radarr", value)}
            />
            <Select
              label={
                <HelpLabel
                  label="Sonarr Action On Missing"
                  help="Action to apply in Sonarr when a source folder stays missing after grace period."
                />
              }
              data={["none", "unmonitor", "delete"]}
              value={draft.cleanup.sonarr_action_on_missing}
              onChange={(value) => setCleanupAction("sonarr", value)}
            />
            <NumberInput
              label={
                <HelpLabel
                  label="Missing Grace Seconds"
                  help="How long an item may remain missing before unmonitor/delete actions are applied."
                />
              }
              value={draft.cleanup.missing_grace_seconds}
              min={0}
              onChange={(value) =>
                setSectionField("cleanup", "missing_grace_seconds", Number(value) || 0)
              }
            />
          </Group>
        </Stack>
      </Card>

      <Card withBorder>
        <Title order={4}>Runtime</Title>
        <Stack mt="sm">
          <Group grow align="flex-end">
            <NumberInput
              label={
                <HelpLabel
                  label="Debounce Seconds"
                  help="Event burst window before running a reconcile cycle."
                />
              }
              value={draft.runtime.debounce_seconds}
              min={0}
              onChange={(value) => setSectionField("runtime", "debounce_seconds", Number(value) || 0)}
            />
            <NumberInput
              label={
                <HelpLabel
                  label="Maintenance Interval (minutes)"
                  help="Interval for periodic full maintenance reconciles. Set 0 to disable periodic runs."
                />
              }
              value={draft.runtime.maintenance_interval_minutes}
              min={0}
              onChange={(value) =>
                setSectionField("runtime", "maintenance_interval_minutes", Number(value) || 0)
              }
            />
            <NumberInput
              label={
                <HelpLabel
                  label="Arr Root Poll Interval (minutes)"
                  help="How often Arr root folders are polled to auto-trigger reconcile when shadow roots appear later."
                />
              }
              value={draft.runtime.arr_root_poll_interval_minutes}
              min={0}
              onChange={(value) =>
                setSectionField("runtime", "arr_root_poll_interval_minutes", Number(value) || 0)
              }
            />
          </Group>
          <TagsInput
            label={
              <HelpLabel
                label="Scan Video Extensions"
                help="File extensions treated as video files while detecting media folders."
              />
            }
            placeholder="Add extension and press Enter"
            data={VIDEO_EXTENSION_SUGGESTIONS}
            value={(draft.runtime.scan_video_extensions ?? []).map((value) =>
              String(value).replace(/^\.+/, "")
            )}
            splitChars={[",", " "]}
            clearable
            acceptValueOnBlur
            onChange={(values) =>
              setSectionField("runtime", "scan_video_extensions", normalizeVideoExtensions(values))
            }
          />
        </Stack>
      </Card>

      <Card withBorder>
        <Title order={4}>Analysis</Title>
        <Stack mt="sm">
          <Group>
            <Checkbox
              label={<HelpLabel label="Use NFO" help="Includes NFO text tokens in quality detection." />}
              checked={draft.analysis.use_nfo}
              onChange={(event) => setSectionField("analysis", "use_nfo", event.currentTarget.checked)}
            />
            <Checkbox
              label={
                <HelpLabel
                  label="Use Media Probe"
                  help="Includes media probe tokens in quality detection when available."
                />
              }
              checked={draft.analysis.use_media_probe}
              onChange={(event) =>
                setSectionField("analysis", "use_media_probe", event.currentTarget.checked)
              }
            />
          </Group>
          <TextInput
            label={
              <HelpLabel
                label="Media Probe Binary"
                help="Executable name or absolute path used for media probing (for example ffprobe)."
              />
            }
            value={draft.analysis.media_probe_bin}
            onChange={(event) => setSectionField("analysis", "media_probe_bin", event.currentTarget.value)}
          />
        </Stack>
      </Card>

      {diffText && (
        <Card withBorder>
          <Title order={4}>Draft Diff</Title>
          <Code block mt="sm">
            {diffText}
          </Code>
        </Card>
      )}

      {showYamlPreview && yamlPreview && (
        <Card withBorder>
          <Title order={4}>YAML Preview</Title>
          <Code block mt="sm">
            {yamlPreview}
          </Code>
        </Card>
      )}

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
