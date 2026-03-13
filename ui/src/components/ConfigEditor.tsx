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
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { useEffect, useState } from "react";
import { getFsRoots } from "../api/client";
import type { ConfigModel, Issue } from "../types/config";
import RadarrSection from "./config/RadarrSection";
import SonarrSection from "./config/SonarrSection";
import { parseCommaSeparated } from "./config/ruleParsers";
import DirectoryPickerModal from "./DirectoryPickerModal";

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
          <TextInput
            label="Scan Video Extensions (comma-separated)"
            value={(draft.runtime.scan_video_extensions ?? []).join(", ")}
            onChange={(event) =>
              setSectionField(
                "runtime",
                "scan_video_extensions",
                parseCommaSeparated(event.currentTarget.value)
              )
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
            <Checkbox
              label="Legacy unmonitor_on_delete"
              checked={draft.cleanup.unmonitor_on_delete}
              onChange={(event) =>
                setSectionField("cleanup", "unmonitor_on_delete", event.currentTarget.checked)
              }
            />
            <Checkbox
              label="Legacy delete_from_radarr_on_missing"
              checked={draft.cleanup.delete_from_radarr_on_missing}
              onChange={(event) =>
                setSectionField("cleanup", "delete_from_radarr_on_missing", event.currentTarget.checked)
              }
            />
            <Checkbox
              label="Legacy delete_from_sonarr_on_missing"
              checked={draft.cleanup.delete_from_sonarr_on_missing}
              onChange={(event) =>
                setSectionField("cleanup", "delete_from_sonarr_on_missing", event.currentTarget.checked)
              }
            />
          </Group>
          <Group grow align="flex-end">
            <Select
              label="Radarr Action On Missing"
              data={["none", "unmonitor", "delete"]}
              value={draft.cleanup.radarr_action_on_missing}
              onChange={(value) =>
                setSectionField("cleanup", "radarr_action_on_missing", value ?? "none")
              }
            />
            <Select
              label="Sonarr Action On Missing"
              data={["none", "unmonitor", "delete"]}
              value={draft.cleanup.sonarr_action_on_missing}
              onChange={(value) =>
                setSectionField("cleanup", "sonarr_action_on_missing", value ?? "none")
              }
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
        <Stack mt="sm">
          {draft.paths.root_mappings.map((mapping, index) => (
            <Card key={`mapping-${index}`} withBorder>
              <Stack>
                <Group grow align="end">
                  <TextInput
                    label={`Nested Root ${index + 1}`}
                    value={mapping.nested_root}
                    onChange={(event) => setRootMapping(index, "nested_root", event.currentTarget.value)}
                  />
                  <Button variant="light" onClick={() => setPickerTarget({ index, key: "nested_root" })}>
                    Pick Directory
                  </Button>
                </Group>
                <Group grow align="end">
                  <TextInput
                    label={`Shadow Root ${index + 1}`}
                    value={mapping.shadow_root}
                    onChange={(event) => setRootMapping(index, "shadow_root", event.currentTarget.value)}
                  />
                  <Button variant="light" onClick={() => setPickerTarget({ index, key: "shadow_root" })}>
                    Pick Directory
                  </Button>
                </Group>
                <Group justify="flex-end">
                  <Button color="red" variant="subtle" onClick={() => removeRootMapping(index)}>
                    Remove Mapping
                  </Button>
                </Group>
              </Stack>
            </Card>
          ))}
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
