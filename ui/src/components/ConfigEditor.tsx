import {
  ActionIcon,
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
  Table,
  TagsInput,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useEffect, useState } from "react";
import { getFsRoots } from "../api/client";
import type { ConfigModel, Issue } from "../types/config";
import RadarrSection from "./config/RadarrSection";
import SonarrSection from "./config/SonarrSection";
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

      <Card withBorder>
        <Title order={4}>General</Title>
        <Stack mt="sm">
          <Group grow align="flex-end">
            <NumberInput
              label="Debounce Seconds"
              value={draft.runtime.debounce_seconds}
              min={0}
              onChange={(value) => setSectionField("runtime", "debounce_seconds", Number(value) || 0)}
            />
            <NumberInput
              label="Maintenance Interval (minutes)"
              value={draft.runtime.maintenance_interval_minutes}
              min={0}
              onChange={(value) =>
                setSectionField("runtime", "maintenance_interval_minutes", Number(value) || 0)
              }
            />
            <NumberInput
              label="Arr Root Poll Interval (minutes)"
              value={draft.runtime.arr_root_poll_interval_minutes}
              min={0}
              onChange={(value) =>
                setSectionField("runtime", "arr_root_poll_interval_minutes", Number(value) || 0)
              }
            />
          </Group>
          <TagsInput
            label="Scan Video Extensions"
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
        <Title order={4}>Cleanup</Title>
        <Stack mt="sm">
          <Group>
            <Checkbox
              label="Remove orphaned links"
              checked={draft.cleanup.remove_orphaned_links}
              onChange={(event) =>
                setSectionField("cleanup", "remove_orphaned_links", event.currentTarget.checked)
              }
            />
          </Group>
          <Group grow align="flex-end">
            <Select
              label="Radarr Action On Missing"
              data={["none", "unmonitor", "delete"]}
              value={draft.cleanup.radarr_action_on_missing}
              onChange={(value) => setCleanupAction("radarr", value)}
            />
            <Select
              label="Sonarr Action On Missing"
              data={["none", "unmonitor", "delete"]}
              value={draft.cleanup.sonarr_action_on_missing}
              onChange={(value) => setCleanupAction("sonarr", value)}
            />
            <NumberInput
              label="Missing Grace Seconds"
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
        <Title order={4}>Analysis</Title>
        <Stack mt="sm">
          <Group>
            <Checkbox
              label="Use NFO"
              checked={draft.analysis.use_nfo}
              onChange={(event) => setSectionField("analysis", "use_nfo", event.currentTarget.checked)}
            />
            <Checkbox
              label="Use Media Probe"
              checked={draft.analysis.use_media_probe}
              onChange={(event) =>
                setSectionField("analysis", "use_media_probe", event.currentTarget.checked)
              }
            />
          </Group>
          <TextInput
            label="Media Probe Binary"
            value={draft.analysis.media_probe_bin}
            onChange={(event) => setSectionField("analysis", "media_probe_bin", event.currentTarget.value)}
          />
        </Stack>
      </Card>

      <Card withBorder>
        <Title order={4}>Ingest</Title>
        <Stack mt="sm">
          <Switch
            label="Enabled"
            checked={draft.ingest.enabled}
            onChange={(event) => setSectionField("ingest", "enabled", event.currentTarget.checked)}
          />
          <Group grow align="flex-end">
            <NumberInput
              label="Minimum Age Seconds"
              value={draft.ingest.min_age_seconds}
              min={0}
              onChange={(value) => setSectionField("ingest", "min_age_seconds", Number(value) || 0)}
            />
            <Select
              label="Collision Policy"
              data={["qualify", "skip"]}
              value={draft.ingest.collision_policy}
              onChange={(value) => setSectionField("ingest", "collision_policy", value ?? "qualify")}
            />
            <TextInput
              label="Quarantine Root"
              value={draft.ingest.quarantine_root}
              onChange={(event) => setSectionField("ingest", "quarantine_root", event.currentTarget.value)}
            />
          </Group>
        </Stack>
      </Card>

      <RadarrSection
        value={draft.radarr}
        onChange={(nextRadarr) => onChange({ ...draft, radarr: nextRadarr })}
      />

      <SonarrSection
        value={draft.sonarr}
        onChange={(nextSonarr) => onChange({ ...draft, sonarr: nextSonarr })}
      />

      <Card withBorder>
        <Group justify="space-between">
          <Title order={4}>Root Mappings</Title>
          <Button variant="light" onClick={addRootMapping}>
            Add Mapping
          </Button>
        </Group>
        <Table mt="sm" verticalSpacing={6} horizontalSpacing="xs" layout="fixed">
          <Table.Thead>
            <Table.Tr>
              <Table.Th py={6} fz="sm">Nested Root</Table.Th>
              <Table.Th py={6} w={140} />
              <Table.Th py={6} fz="sm">Shadow Root</Table.Th>
              <Table.Th py={6} w={140} />
              <Table.Th py={6} w={44} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {draft.paths.root_mappings.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed" size="sm">No mappings yet. Use Add Mapping.</Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              draft.paths.root_mappings.map((mapping, index) => (
                <Table.Tr key={`mapping-${index}`}>
                  <Table.Td>
                    <TextInput
                      size="sm"
                      aria-label={`Nested Root ${index + 1}`}
                      value={mapping.nested_root}
                      onChange={(event) => setRootMapping(index, "nested_root", event.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="sm"
                      variant="light"
                      fullWidth
                      onClick={() => setPickerTarget({ index, key: "nested_root" })}
                    >
                      Pick Directory
                    </Button>
                  </Table.Td>
                  <Table.Td>
                    <TextInput
                      size="sm"
                      aria-label={`Shadow Root ${index + 1}`}
                      value={mapping.shadow_root}
                      onChange={(event) => setRootMapping(index, "shadow_root", event.currentTarget.value)}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="sm"
                      variant="light"
                      fullWidth
                      onClick={() => setPickerTarget({ index, key: "shadow_root" })}
                    >
                      Pick Directory
                    </Button>
                  </Table.Td>
                  <Table.Td>
                    <ActionIcon
                      size="sm"
                      color="red"
                      variant="subtle"
                      aria-label="Remove mapping"
                      onClick={() => removeRootMapping(index)}
                    >
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
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
