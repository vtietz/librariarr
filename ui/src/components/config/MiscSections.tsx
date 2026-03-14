import {
  Card,
  Checkbox,
  Group,
  NumberInput,
  Select,
  Stack,
  Switch,
  TagsInput,
  TextInput,
  Title
} from "@mantine/core";
import type { ConfigModel } from "../../types/config";
import HelpLabel from "./HelpLabel";

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
  onSetSectionField: <T extends keyof ConfigModel>(
    section: T,
    field: keyof ConfigModel[T],
    value: unknown
  ) => void;
  onSetCleanupAction: (target: "radarr" | "sonarr", value: string | null) => void;
};

export default function MiscSections({ draft, onSetSectionField, onSetCleanupAction }: Props) {
  return (
    <>
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
            onChange={(event) => onSetSectionField("ingest", "enabled", event.currentTarget.checked)}
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
              onChange={(value) => onSetSectionField("ingest", "min_age_seconds", Number(value) || 0)}
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
              onChange={(value) => onSetSectionField("ingest", "collision_policy", value ?? "qualify")}
            />
            <TextInput
              label={
                <HelpLabel
                  label="Quarantine Root"
                  help="Optional folder where failed ingest moves can be placed for recovery."
                />
              }
              value={draft.ingest.quarantine_root}
              onChange={(event) => onSetSectionField("ingest", "quarantine_root", event.currentTarget.value)}
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
                onSetSectionField("cleanup", "remove_orphaned_links", event.currentTarget.checked)
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
              onChange={(value) => onSetCleanupAction("radarr", value)}
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
              onChange={(value) => onSetCleanupAction("sonarr", value)}
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
                onSetSectionField("cleanup", "missing_grace_seconds", Number(value) || 0)
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
              onChange={(value) => onSetSectionField("runtime", "debounce_seconds", Number(value) || 0)}
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
                onSetSectionField("runtime", "maintenance_interval_minutes", Number(value) || 0)
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
                onSetSectionField("runtime", "arr_root_poll_interval_minutes", Number(value) || 0)
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
              onSetSectionField("runtime", "scan_video_extensions", normalizeVideoExtensions(values))
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
              onChange={(event) => onSetSectionField("analysis", "use_nfo", event.currentTarget.checked)}
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
                onSetSectionField("analysis", "use_media_probe", event.currentTarget.checked)
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
            onChange={(event) => onSetSectionField("analysis", "media_probe_bin", event.currentTarget.value)}
          />
        </Stack>
      </Card>
    </>
  );
}
