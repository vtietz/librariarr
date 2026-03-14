export type Issue = {
  severity: string;
  message: string;
};

export type RootMapping = {
  nested_root: string;
  shadow_root: string;
};

export type ConfigModel = {
  paths: {
    root_mappings: RootMapping[];
    exclude_paths: string[];
  };
  radarr: {
    enabled: boolean;
    sync_enabled: boolean;
    url: string;
    api_key: string;
    refresh_debounce_seconds: number;
    auto_add_unmatched: boolean;
    auto_add_quality_profile_id: number | null;
    auto_add_search_on_add: boolean;
    auto_add_monitored: boolean;
    mapping: {
      quality_map: Array<{ match: string[]; target_id: number }>;
      custom_format_map: Array<{ match: string[]; format_id: number }>;
    };
  };
  sonarr: {
    enabled: boolean;
    sync_enabled: boolean;
    url: string;
    api_key: string;
    refresh_debounce_seconds: number;
    auto_add_unmatched: boolean;
    auto_add_quality_profile_id: number | null;
    auto_add_language_profile_id: number | null;
    auto_add_search_on_add: boolean;
    auto_add_monitored: boolean;
    auto_add_season_folder: boolean;
    mapping: {
      quality_profile_map: Array<{ match: string[]; profile_id: number }>;
      language_profile_map: Array<{ match: string[]; profile_id: number }>;
    };
  };
  cleanup: {
    remove_orphaned_links: boolean;
    radarr_action_on_missing: string;
    sonarr_action_on_missing: string;
    missing_grace_seconds: number;
  };
  runtime: {
    debounce_seconds: number;
    maintenance_interval_minutes: number;
    arr_root_poll_interval_minutes: number;
    scan_video_extensions: string[] | null;
  };
  analysis: {
    use_nfo: boolean;
    use_media_probe: boolean;
    media_probe_bin: string;
  };
  ingest: {
    enabled: boolean;
    min_age_seconds: number;
    collision_policy: "qualify" | "skip";
    quarantine_root: string;
  };
};

export type ConfigResponse = {
  source: string;
  checksum: string;
  yaml: string;
  has_draft: boolean;
  config: ConfigModel;
};

export type ValidateResponse = {
  valid?: boolean;
  saved?: boolean;
  checksum: string;
  issues: Issue[];
  config?: ConfigModel;
  runtime_restart_recommended?: boolean;
};
