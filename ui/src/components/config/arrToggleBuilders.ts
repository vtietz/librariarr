import type { ConfigModel } from "../../types/config";
import type { ToggleItem } from "./ArrBaseSection";

export function buildRadarrToggles(
  value: ConfigModel["radarr"],
  setField: (field: keyof ConfigModel["radarr"], checked: boolean) => void
): ToggleItem[] {
  return [
    {
      label: "Enabled",
      checked: value.enabled,
      kind: "switch",
      onChange: (checked) => setField("enabled", checked)
    },
    {
      label: "Sync enabled",
      checked: value.sync_enabled,
      onChange: (checked) => setField("sync_enabled", checked)
    },
    {
      label: "Auto-add unmatched",
      checked: value.auto_add_unmatched,
      onChange: (checked) => setField("auto_add_unmatched", checked)
    },
    {
      label: "Auto-add search on add",
      checked: value.auto_add_search_on_add,
      onChange: (checked) => setField("auto_add_search_on_add", checked)
    },
    {
      label: "Auto-add monitored",
      checked: value.auto_add_monitored,
      onChange: (checked) => setField("auto_add_monitored", checked)
    }
  ];
}

export function buildSonarrToggles(
  value: ConfigModel["sonarr"],
  setField: (field: keyof ConfigModel["sonarr"], checked: boolean) => void
): ToggleItem[] {
  return [
    {
      label: "Enabled",
      checked: value.enabled,
      kind: "switch",
      onChange: (checked) => setField("enabled", checked)
    },
    {
      label: "Sync enabled",
      checked: value.sync_enabled,
      onChange: (checked) => setField("sync_enabled", checked)
    },
    {
      label: "Auto-add unmatched",
      checked: value.auto_add_unmatched,
      onChange: (checked) => setField("auto_add_unmatched", checked)
    },
    {
      label: "Auto-add search on add",
      checked: value.auto_add_search_on_add,
      onChange: (checked) => setField("auto_add_search_on_add", checked)
    },
    {
      label: "Auto-add monitored",
      checked: value.auto_add_monitored,
      onChange: (checked) => setField("auto_add_monitored", checked)
    },
    {
      label: "Auto-add season folder",
      checked: value.auto_add_season_folder,
      onChange: (checked) => setField("auto_add_season_folder", checked)
    }
  ];
}
