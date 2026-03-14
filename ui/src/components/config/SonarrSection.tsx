import { Group, NumberInput, Select, Text } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import {
  getSonarrLanguageProfiles,
  getSonarrProfiles,
  getSonarrTags,
  testSonarrConnection
} from "../../api/client";
import type { ConfigModel } from "../../types/config";
import { toOpenToolUrl } from "../../utils/toolUrl";
import ArrBaseSection from "./ArrBaseSection";
import { buildSonarrToggles } from "./arrToggleBuilders";
import RuleEditor from "./RuleEditor";
import { addRule, removeRuleAt, updateRuleAt } from "./ruleListState";

type Props = {
  value: ConfigModel["sonarr"];
  onChange: (next: ConfigModel["sonarr"]) => void;
};

export default function SonarrSection({ value, onChange }: Props) {
  const [testing, setTesting] = useState(false);
  const [testStatus, setTestStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [qualityProfileOptions, setQualityProfileOptions] = useState<
    Array<{ value: string; label: string }>
  >([]);
  const [languageProfileOptions, setLanguageProfileOptions] = useState<
    Array<{ value: string; label: string }>
  >([]);
  const [metadataWarning, setMetadataWarning] = useState<string | null>(null);

  const setField = (field: keyof ConfigModel["sonarr"], fieldValue: unknown) => {
    onChange({ ...value, [field]: fieldValue });
  };

  const setMappingField = <T extends keyof ConfigModel["sonarr"]["mapping"]>(
    field: T,
    nextValue: ConfigModel["sonarr"]["mapping"][T]
  ) => {
    onChange({
      ...value,
      mapping: {
        ...value.mapping,
        [field]: nextValue
      }
    });
  };

  useEffect(() => {
    let alive = true;
    void (async () => {
      const [tagsResult, qualityProfilesResult, languageProfilesResult] = await Promise.allSettled([
        getSonarrTags(),
        getSonarrProfiles(),
        getSonarrLanguageProfiles()
      ]);
      if (!alive) {
        return;
      }

      const tags = tagsResult.status === "fulfilled" ? tagsResult.value : [];
      const qualityProfiles =
        qualityProfilesResult.status === "fulfilled" ? qualityProfilesResult.value : [];
      const languageProfiles =
        languageProfilesResult.status === "fulfilled" ? languageProfilesResult.value : [];

      const failedSources: string[] = [];
      if (tagsResult.status === "rejected") {
        failedSources.push("tags");
      }
      if (qualityProfilesResult.status === "rejected") {
        failedSources.push("quality profiles");
      }
      if (languageProfilesResult.status === "rejected") {
        failedSources.push("language profiles");
      }
      setMetadataWarning(
        failedSources.length > 0
          ? `Some Sonarr options could not be loaded: ${failedSources.join(", ")}. Suggestions may be incomplete.`
          : null
      );

      const nextTags = tags
          .map((tag) => String(tag.label ?? "").trim().toLowerCase())
          .filter((tag) => tag.length > 0);
      setTagOptions(Array.from(new Set(nextTags)).sort((left, right) => left.localeCompare(right)));

      const nextQualityProfiles = qualityProfiles
        .map((profile) => {
          const id = typeof profile.id === "number" ? profile.id : Number.NaN;
          if (!Number.isFinite(id)) {
            return null;
          }
          const name = String(profile.name ?? "").trim();
          return {
            value: String(id),
            label: name.length > 0 ? `${id} - ${name}` : String(id)
          };
        })
        .filter((item): item is { value: string; label: string } => item != null)
        .sort((left, right) => Number(left.value) - Number(right.value));
      setQualityProfileOptions(nextQualityProfiles);

      const nextLanguageProfiles = languageProfiles
        .map((profile) => {
          const id = typeof profile.id === "number" ? profile.id : Number.NaN;
          if (!Number.isFinite(id)) {
            return null;
          }
          const name = String(profile.name ?? "").trim();
          return {
            value: String(id),
            label: name.length > 0 ? `${id} - ${name}` : String(id)
          };
        })
        .filter((item): item is { value: string; label: string } => item != null)
        .sort((left, right) => Number(left.value) - Number(right.value));
      setLanguageProfileOptions(nextLanguageProfiles);
    })();

    return () => {
      alive = false;
    };
  }, []);

  const defaultMatchTags = useMemo(() => (tagOptions.length > 0 ? [tagOptions[0]] : []), [tagOptions]);
  const defaultQualityProfileId = useMemo(() => {
    if (qualityProfileOptions.length === 0) {
      return 1;
    }
    return Number(qualityProfileOptions[0]?.value) || 1;
  }, [qualityProfileOptions]);
  const defaultLanguageProfileId = useMemo(() => {
    if (languageProfileOptions.length === 0) {
      return 1;
    }
    return Number(languageProfileOptions[0]?.value) || 1;
  }, [languageProfileOptions]);

  return (
    <ArrBaseSection
      title="Sonarr"
      toggles={buildSonarrToggles(value, (field, checked) => setField(field, checked))}
      urlLabel="Sonarr URL"
      urlValue={value.url}
      onUrlChange={(nextValue) => setField("url", nextValue)}
      apiKeyLabel="Sonarr API Key"
      apiKeyValue={value.api_key}
      onApiKeyChange={(nextValue) => setField("api_key", nextValue)}
      openLabel="Open Sonarr"
      openHref={toOpenToolUrl(value.url, 8989) ?? undefined}
      testLabel="Test Sonarr Connection"
      onTest={async () => {
        setTesting(true);
        try {
          setTestStatus(await testSonarrConnection(value.url, value.api_key));
        } catch {
          setTestStatus({ ok: false, message: "Failed to connect to Sonarr" });
        } finally {
          setTesting(false);
        }
      }}
      testing={testing}
      testStatus={testStatus}
    >
      <Group grow align="flex-end">
        <NumberInput
          label="Refresh Debounce Seconds"
          value={value.refresh_debounce_seconds}
          min={0}
          onChange={(fieldValue) => setField("refresh_debounce_seconds", Number(fieldValue) || 0)}
        />
        {(() => {
          const currentValue =
            value.auto_add_quality_profile_id == null
              ? null
              : String(value.auto_add_quality_profile_id);
          const hasCurrentOption =
            currentValue == null
              ? true
              : qualityProfileOptions.some((option) => option.value === currentValue);
          const options =
            currentValue == null || hasCurrentOption
              ? qualityProfileOptions
              : [
                  ...qualityProfileOptions,
                  {
                    value: currentValue,
                    label: `${currentValue} (configured, unavailable)`
                  }
                ];

          return (
            <Select
              label="Auto-add Quality Profile ID"
              data={options}
              value={currentValue}
              searchable
              clearable
              nothingFoundMessage="No profiles"
              onChange={(nextValue) =>
                setField(
                  "auto_add_quality_profile_id",
                  nextValue == null ? null : Number(nextValue)
                )
              }
            />
          );
        })()}
        {(() => {
          const currentValue =
            value.auto_add_language_profile_id == null
              ? null
              : String(value.auto_add_language_profile_id);
          const hasCurrentOption =
            currentValue == null
              ? true
              : languageProfileOptions.some((option) => option.value === currentValue);
          const options =
            currentValue == null || hasCurrentOption
              ? languageProfileOptions
              : [
                  ...languageProfileOptions,
                  {
                    value: currentValue,
                    label: `${currentValue} (configured, unavailable)`
                  }
                ];

          return (
            <Select
              label="Auto-add Language Profile ID"
              data={options}
              value={currentValue}
              searchable
              clearable
              nothingFoundMessage="No profiles"
              onChange={(nextValue) =>
                setField(
                  "auto_add_language_profile_id",
                  nextValue == null ? null : Number(nextValue)
                )
              }
            />
          );
        })()}
      </Group>

      {metadataWarning ? (
        <Text size="xs" c="yellow">
          {metadataWarning}
        </Text>
      ) : null}

        <RuleEditor
          title="Sonarr Quality Profile Map"
          idLabel="Profile ID"
          tagOptions={tagOptions}
          idOptions={qualityProfileOptions}
          rows={value.mapping.quality_profile_map}
          keyPrefix="sonarr-quality"
          readId={(row) => row.profile_id}
          onAdd={() =>
            setMappingField(
              "quality_profile_map",
              addRule(value.mapping.quality_profile_map, () => ({
                match: defaultMatchTags,
                profile_id: defaultQualityProfileId
              }))
            )
          }
          onRemove={(index) =>
            setMappingField("quality_profile_map", removeRuleAt(value.mapping.quality_profile_map, index))
          }
          onMatchChange={(index, match) =>
            setMappingField(
              "quality_profile_map",
              updateRuleAt(value.mapping.quality_profile_map, index, (row) => ({ ...row, match }))
            )
          }
          onIdChange={(index, profileId) =>
            setMappingField(
              "quality_profile_map",
              updateRuleAt(value.mapping.quality_profile_map, index, (row) => ({
                ...row,
                profile_id: profileId
              }))
            )
          }
        />

        <RuleEditor
          title="Sonarr Language Profile Map"
          idLabel="Profile ID"
          tagOptions={tagOptions}
          idOptions={languageProfileOptions}
          rows={value.mapping.language_profile_map}
          keyPrefix="sonarr-language"
          readId={(row) => row.profile_id}
          onAdd={() =>
            setMappingField(
              "language_profile_map",
              addRule(value.mapping.language_profile_map, () => ({
                match: defaultMatchTags,
                profile_id: defaultLanguageProfileId
              }))
            )
          }
          onRemove={(index) =>
            setMappingField("language_profile_map", removeRuleAt(value.mapping.language_profile_map, index))
          }
          onMatchChange={(index, match) =>
            setMappingField(
              "language_profile_map",
              updateRuleAt(value.mapping.language_profile_map, index, (row) => ({ ...row, match }))
            )
          }
          onIdChange={(index, profileId) =>
            setMappingField(
              "language_profile_map",
              updateRuleAt(value.mapping.language_profile_map, index, (row) => ({
                ...row,
                profile_id: profileId
              }))
            )
          }
        />
    </ArrBaseSection>
  );
}
