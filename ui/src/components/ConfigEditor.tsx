import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  Code,
  Group,
  NumberInput,
  Stack,
  Switch,
  Text,
  TextInput,
  Title
} from "@mantine/core";
import { useEffect, useState } from "react";
import {
  getFsRoots,
  testRadarrConnection,
  testSonarrConnection
} from "../api/client";
import DirectoryPickerModal from "./DirectoryPickerModal";
import { toOpenToolUrl } from "../utils/toolUrl";
import type { ConfigModel, Issue } from "../types/config";

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
  const [radarrTestStatus, setRadarrTestStatus] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const [sonarrTestStatus, setSonarrTestStatus] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const [radarrTesting, setRadarrTesting] = useState(false);
  const [sonarrTesting, setSonarrTesting] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const roots = await getFsRoots();
        setPickerRoots(roots);
      } catch {
        setPickerRoots([]);
      }
    })();
  }, []);

  const setRadarr = (field: keyof ConfigModel["radarr"], value: unknown) => {
    onChange({
      ...draft,
      radarr: {
        ...draft.radarr,
        [field]: value
      }
    });
  };

  const setSonarr = (field: keyof ConfigModel["sonarr"], value: unknown) => {
    onChange({
      ...draft,
      sonarr: {
        ...draft.sonarr,
        [field]: value
      }
    });
  };

  const setRuntime = (field: keyof ConfigModel["runtime"], value: number) => {
    onChange({
      ...draft,
      runtime: {
        ...draft.runtime,
        [field]: value
      }
    });
  };

  const setRootMapping = (index: number, key: "nested_root" | "shadow_root", value: string) => {
    const nextMappings = draft.paths.root_mappings.map((mapping, mapIndex) => {
      if (mapIndex !== index) {
        return mapping;
      }
      return {
        ...mapping,
        [key]: value
      };
    });

    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        root_mappings: nextMappings
      }
    });
  };

  const removeRootMapping = (index: number) => {
    const nextMappings = draft.paths.root_mappings.filter((_, mapIndex) => mapIndex !== index);
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        root_mappings: nextMappings
      }
    });
  };

  const addRootMapping = () => {
    onChange({
      ...draft,
      paths: {
        ...draft.paths,
        root_mappings: [
          ...draft.paths.root_mappings,
          {
            nested_root: "",
            shadow_root: ""
          }
        ]
      }
    });
  };

  const startPicker = (index: number, key: "nested_root" | "shadow_root") => {
    setPickerTarget({ index, key });
  };

  const applyPickedPath = (path: string) => {
    if (!pickerTarget) {
      return;
    }
    setRootMapping(pickerTarget.index, pickerTarget.key, path);
    setPickerTarget(null);
  };

  const runRadarrConnectionTest = async () => {
    setRadarrTesting(true);
    try {
      const result = await testRadarrConnection(draft.radarr.url, draft.radarr.api_key);
      setRadarrTestStatus(result);
    } catch (error: unknown) {
      const message =
        typeof error === "object" &&
        error !== null &&
        "message" in error &&
        typeof (error as { message?: unknown }).message === "string"
          ? (error as { message: string }).message
          : "Failed to connect to Radarr";
      setRadarrTestStatus({ ok: false, message });
    } finally {
      setRadarrTesting(false);
    }
  };

  const runSonarrConnectionTest = async () => {
    setSonarrTesting(true);
    try {
      const result = await testSonarrConnection(draft.sonarr.url, draft.sonarr.api_key);
      setSonarrTestStatus(result);
    } catch (error: unknown) {
      const message =
        typeof error === "object" &&
        error !== null &&
        "message" in error &&
        typeof (error as { message?: unknown }).message === "string"
          ? (error as { message: string }).message
          : "Failed to connect to Sonarr";
      setSonarrTestStatus({ ok: false, message });
    } finally {
      setSonarrTesting(false);
    }
  };

  const pickerInitialPath =
    pickerTarget == null
      ? ""
      : draft.paths.root_mappings[pickerTarget.index]?.[pickerTarget.key] ?? "";
  const radarrOpenUrl = toOpenToolUrl(draft.radarr.url, 7878);
  const sonarrOpenUrl = toOpenToolUrl(draft.sonarr.url, 8989);

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
        <Group grow align="flex-end" mt="sm">
          <NumberInput
            label="Debounce Seconds"
            value={draft.runtime.debounce_seconds}
            min={1}
            onChange={(value) => setRuntime("debounce_seconds", Number(value) || 1)}
          />
          <NumberInput
            label="Maintenance Interval (minutes)"
            value={draft.runtime.maintenance_interval_minutes}
            min={0}
            onChange={(value) =>
              setRuntime("maintenance_interval_minutes", Number(value) || 0)
            }
          />
          <NumberInput
            label="Arr Root Poll Interval (minutes)"
            value={draft.runtime.arr_root_poll_interval_minutes}
            min={0}
            onChange={(value) =>
              setRuntime("arr_root_poll_interval_minutes", Number(value) || 0)
            }
          />
        </Group>
      </Card>

      <Card withBorder>
        <Title order={4}>Radarr</Title>
        <Group mt="sm" mb="sm">
          <Switch
            label="Enabled"
            checked={draft.radarr.enabled}
            onChange={(event) => setRadarr("enabled", event.currentTarget.checked)}
          />
          <Checkbox
            label="Sync enabled"
            checked={draft.radarr.sync_enabled}
            onChange={(event) => setRadarr("sync_enabled", event.currentTarget.checked)}
          />
          <Checkbox
            label="Auto-add unmatched"
            checked={draft.radarr.auto_add_unmatched}
            onChange={(event) => setRadarr("auto_add_unmatched", event.currentTarget.checked)}
          />
        </Group>
        <Stack>
          <TextInput
            label="Radarr URL"
            value={draft.radarr.url}
            onChange={(event) => setRadarr("url", event.currentTarget.value)}
          />
          <TextInput
            label="Radarr API Key"
            value={draft.radarr.api_key}
            onChange={(event) => setRadarr("api_key", event.currentTarget.value)}
          />
          <Group>
            <Button
              component="a"
              variant="default"
              href={radarrOpenUrl ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
              disabled={!radarrOpenUrl}
            >
              Open Radarr
            </Button>
            <Button
              variant="light"
              onClick={runRadarrConnectionTest}
              loading={radarrTesting}
            >
              Test Radarr Connection
            </Button>
            {radarrTestStatus ? (
              <Text size="sm" c={radarrTestStatus.ok ? "green" : "red"}>
                {radarrTestStatus.message}
              </Text>
            ) : null}
          </Group>
        </Stack>
      </Card>

      <Card withBorder>
        <Title order={4}>Sonarr</Title>
        <Group mt="sm" mb="sm">
          <Switch
            label="Enabled"
            checked={draft.sonarr.enabled}
            onChange={(event) => setSonarr("enabled", event.currentTarget.checked)}
          />
          <Checkbox
            label="Sync enabled"
            checked={draft.sonarr.sync_enabled}
            onChange={(event) => setSonarr("sync_enabled", event.currentTarget.checked)}
          />
          <Checkbox
            label="Auto-add unmatched"
            checked={draft.sonarr.auto_add_unmatched}
            onChange={(event) => setSonarr("auto_add_unmatched", event.currentTarget.checked)}
          />
        </Group>
        <Stack>
          <TextInput
            label="Sonarr URL"
            value={draft.sonarr.url}
            onChange={(event) => setSonarr("url", event.currentTarget.value)}
          />
          <TextInput
            label="Sonarr API Key"
            value={draft.sonarr.api_key}
            onChange={(event) => setSonarr("api_key", event.currentTarget.value)}
          />
          <Group>
            <Button
              component="a"
              variant="default"
              href={sonarrOpenUrl ?? undefined}
              target="_blank"
              rel="noopener noreferrer"
              disabled={!sonarrOpenUrl}
            >
              Open Sonarr
            </Button>
            <Button
              variant="light"
              onClick={runSonarrConnectionTest}
              loading={sonarrTesting}
            >
              Test Sonarr Connection
            </Button>
            {sonarrTestStatus ? (
              <Text size="sm" c={sonarrTestStatus.ok ? "green" : "red"}>
                {sonarrTestStatus.message}
              </Text>
            ) : null}
          </Group>
        </Stack>
      </Card>

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
                    onChange={(event) =>
                      setRootMapping(index, "nested_root", event.currentTarget.value)
                    }
                  />
                  <Button variant="light" onClick={() => startPicker(index, "nested_root")}>
                    Pick Directory
                  </Button>
                </Group>
                <Group grow align="end">
                  <TextInput
                    label={`Shadow Root ${index + 1}`}
                    value={mapping.shadow_root}
                    onChange={(event) =>
                      setRootMapping(index, "shadow_root", event.currentTarget.value)
                    }
                  />
                  <Button variant="light" onClick={() => startPicker(index, "shadow_root")}>
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
        onSelect={applyPickedPath}
      />
    </Stack>
  );
}
