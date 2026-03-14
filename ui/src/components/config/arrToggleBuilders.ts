import type { ConfigModel } from "../../types/config";
import type { ToggleItem } from "./ArrBaseSection";

export function buildRadarrToggles(
  value: ConfigModel["radarr"],
  setField: (field: keyof ConfigModel["radarr"], checked: boolean) => void
): ToggleItem[] {
  return [
    {
      label: "Enabled",
      help: "Turns this integration on or off. Disable to ignore this Arr tool entirely.",
      checked: value.enabled,
      kind: "switch",
      onChange: (checked) => setField("enabled", checked)
    },
    {
      label: "Sync enabled",
      help: "Allows LibrariArr to reconcile and sync paths with this Arr tool.",
      checked: value.sync_enabled,
      onChange: (checked) => setField("sync_enabled", checked)
    },
    {
      label: "Auto-add unmatched",
      help: "Adds folders that do not match existing Arr items as new items automatically.",
      checked: value.auto_add_unmatched,
      onChange: (checked) => setField("auto_add_unmatched", checked)
    },
    {
      label: "Auto-add search on add",
      help: "Triggers an indexer search immediately after an item is auto-added.",
      checked: value.auto_add_search_on_add,
      onChange: (checked) => setField("auto_add_search_on_add", checked)
    },
    {
      label: "Auto-add monitored",
      help: "Sets newly auto-added items to monitored in Arr.",
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
      help: "Turns this integration on or off. Disable to ignore this Arr tool entirely.",
      checked: value.enabled,
      kind: "switch",
      onChange: (checked) => setField("enabled", checked)
    },
    {
      label: "Sync enabled",
      help: "Allows LibrariArr to reconcile and sync paths with this Arr tool.",
      checked: value.sync_enabled,
      onChange: (checked) => setField("sync_enabled", checked)
    },
    {
      label: "Auto-add unmatched",
      help: "Adds folders that do not match existing Arr items as new series automatically.",
      checked: value.auto_add_unmatched,
      onChange: (checked) => setField("auto_add_unmatched", checked)
    },
    {
      label: "Auto-add search on add",
      help: "Triggers an indexer search immediately after a series is auto-added.",
      checked: value.auto_add_search_on_add,
      onChange: (checked) => setField("auto_add_search_on_add", checked)
    },
    {
      label: "Auto-add monitored",
      help: "Sets newly auto-added series to monitored in Sonarr.",
      checked: value.auto_add_monitored,
      onChange: (checked) => setField("auto_add_monitored", checked)
    },
    {
      label: "Auto-add season folder",
      help: "Controls whether newly added series are created with season folders in Sonarr.",
      checked: value.auto_add_season_folder,
      onChange: (checked) => setField("auto_add_season_folder", checked)
    }
  ];
}
