import { Group, NumberInput, Select, Text } from "@mantine/core";
import { useEffect, useMemo, useState } from "react";
import {
  getRadarrCustomFormats,
  getRadarrProfiles,
  getRadarrQualityDefinitions,
  getRadarrTags,
  testRadarrConnection
} from "../../api/client";
import type { ConfigModel } from "../../types/config";
import { toOpenToolUrl } from "../../utils/toolUrl";
import ArrBaseSection from "./ArrBaseSection";
import { buildRadarrToggles } from "./arrToggleBuilders";
import RuleEditor from "./RuleEditor";
import { addRule, removeRuleAt, updateRuleAt } from "./ruleListState";

type Props = {
  value: ConfigModel["radarr"];
  onChange: (next: ConfigModel["radarr"]) => void;
};

export default function RadarrSection({ value, onChange }: Props) {
  const [testing, setTesting] = useState(false);
  const [testStatus, setTestStatus] = useState<{ ok: boolean; message: string } | null>(null);
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [qualityProfileOptions, setQualityProfileOptions] = useState<
    Array<{ value: string; label: string }>
  >([]);
  const [qualityTargetOptions, setQualityTargetOptions] = useState<Array<{ value: string; label: string }>>(
    []
  );
  const [customFormatOptions, setCustomFormatOptions] = useState<Array<{ value: string; label: string }>>(
    []
  );
  const [metadataWarning, setMetadataWarning] = useState<string | null>(null);

  const setField = (field: keyof ConfigModel["radarr"], fieldValue: unknown) => {
    onChange({ ...value, [field]: fieldValue });
  };

  const setMappingField = <T extends keyof ConfigModel["radarr"]["mapping"]>(
    field: T,
    nextValue: ConfigModel["radarr"]["mapping"][T]
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
      const [tagsResult, qualityDefinitionsResult, customFormatsResult, qualityProfilesResult] =
        await Promise.allSettled([
          getRadarrTags(),
          getRadarrQualityDefinitions(),
          getRadarrCustomFormats(),
          getRadarrProfiles()
        ]);
      if (!alive) {
        return;
      }

      const tags = tagsResult.status === "fulfilled" ? tagsResult.value : [];
      const qualityDefinitions =
        qualityDefinitionsResult.status === "fulfilled" ? qualityDefinitionsResult.value : [];
      const customFormats = customFormatsResult.status === "fulfilled" ? customFormatsResult.value : [];
      const qualityProfiles =
        qualityProfilesResult.status === "fulfilled" ? qualityProfilesResult.value : [];

      const failedSources: string[] = [];
      if (tagsResult.status === "rejected") {
        failedSources.push("tags");
      }
      if (qualityDefinitionsResult.status === "rejected") {
        failedSources.push("quality definitions");
      }
      if (customFormatsResult.status === "rejected") {
        failedSources.push("custom formats");
      }
      if (qualityProfilesResult.status === "rejected") {
        failedSources.push("quality profiles");
      }
      setMetadataWarning(
        failedSources.length > 0
          ? `Some Radarr options could not be loaded: ${failedSources.join(", ")}. Suggestions may be incomplete.`
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

      const nextQualityTargets = qualityDefinitions
        .map((definition) => {
          const id = typeof definition.id === "number" ? definition.id : Number.NaN;
          if (!Number.isFinite(id)) {
            return null;
          }
          const name = String(definition.name ?? "").trim();
          return {
            value: String(id),
            label: name.length > 0 ? `${id} - ${name}` : String(id)
          };
        })
        .filter((item): item is { value: string; label: string } => item != null)
        .sort((left, right) => Number(left.value) - Number(right.value));
      setQualityTargetOptions(nextQualityTargets);

      const nextCustomFormatOptions = customFormats
        .map((format) => {
          const id = typeof format.id === "number" ? format.id : Number.NaN;
          if (!Number.isFinite(id)) {
            return null;
          }
          const name = String(format.name ?? "").trim();
          return {
            value: String(id),
            label: name.length > 0 ? `${id} - ${name}` : String(id)
          };
        })
        .filter((item): item is { value: string; label: string } => item != null)
        .sort((left, right) => Number(left.value) - Number(right.value));
      setCustomFormatOptions(nextCustomFormatOptions);
    })();

    return () => {
      alive = false;
    };
  }, []);

  const defaultMatchTags = useMemo(() => (tagOptions.length > 0 ? [tagOptions[0]] : []), [tagOptions]);
  const defaultQualityTargetId = useMemo(() => {
    if (qualityTargetOptions.length === 0) {
      return 1;
    }
    return Number(qualityTargetOptions[0]?.value) || 1;
  }, [qualityTargetOptions]);
  const defaultCustomFormatId = useMemo(() => {
    if (customFormatOptions.length === 0) {
      return 1;
    }
    return Number(customFormatOptions[0]?.value) || 1;
  }, [customFormatOptions]);

  return (
    <ArrBaseSection
      title="Radarr"
      toggles={buildRadarrToggles(value, (field, checked) => setField(field, checked))}
      urlLabel="Radarr URL"
      urlValue={value.url}
      onUrlChange={(nextValue) => setField("url", nextValue)}
      apiKeyLabel="Radarr API Key"
      apiKeyValue={value.api_key}
      onApiKeyChange={(nextValue) => setField("api_key", nextValue)}
      openLabel="Open Radarr"
      openHref={toOpenToolUrl(value.url, 7878) ?? undefined}
      testLabel="Test Radarr Connection"
      onTest={async () => {
        setTesting(true);
        try {
          setTestStatus(await testRadarrConnection(value.url, value.api_key));
        } catch {
          setTestStatus({ ok: false, message: "Failed to connect to Radarr" });
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
      </Group>

      {metadataWarning ? (
        <Text size="xs" c="yellow">
          {metadataWarning}
        </Text>
      ) : null}

        <RuleEditor
          title="Radarr Quality Map"
          idLabel="Target ID"
          tagOptions={tagOptions}
          idOptions={qualityTargetOptions}
          rows={value.mapping.quality_map}
          keyPrefix="radarr-quality"
          readId={(row) => row.target_id}
          onAdd={() =>
            setMappingField(
              "quality_map",
              addRule(value.mapping.quality_map, () => ({
                match: defaultMatchTags,
                target_id: defaultQualityTargetId,
                name: ""
              }))
            )
          }
          onRemove={(index) =>
            setMappingField("quality_map", removeRuleAt(value.mapping.quality_map, index))
          }
          onMatchChange={(index, match) =>
            setMappingField(
              "quality_map",
              updateRuleAt(value.mapping.quality_map, index, (row) => ({ ...row, match }))
            )
          }
          onIdChange={(index, targetId) =>
            setMappingField(
              "quality_map",
              updateRuleAt(value.mapping.quality_map, index, (row) => ({
                ...row,
                target_id: targetId
              }))
            )
          }
          onNameChange={(index, name) =>
            setMappingField(
              "quality_map",
              updateRuleAt(value.mapping.quality_map, index, (row) => ({ ...row, name }))
            )
          }
        />

        <RuleEditor
          title="Radarr Custom Format Map"
          idLabel="Format ID"
          tagOptions={tagOptions}
          idOptions={customFormatOptions}
          rows={value.mapping.custom_format_map}
          keyPrefix="radarr-format"
          readId={(row) => row.format_id}
          onAdd={() =>
            setMappingField(
              "custom_format_map",
              addRule(value.mapping.custom_format_map, () => ({
                match: defaultMatchTags,
                format_id: defaultCustomFormatId,
                name: ""
              }))
            )
          }
          onRemove={(index) =>
            setMappingField("custom_format_map", removeRuleAt(value.mapping.custom_format_map, index))
          }
          onMatchChange={(index, match) =>
            setMappingField(
              "custom_format_map",
              updateRuleAt(value.mapping.custom_format_map, index, (row) => ({ ...row, match }))
            )
          }
          onIdChange={(index, formatId) =>
            setMappingField(
              "custom_format_map",
              updateRuleAt(value.mapping.custom_format_map, index, (row) => ({
                ...row,
                format_id: formatId
              }))
            )
          }
          onNameChange={(index, name) =>
            setMappingField(
              "custom_format_map",
              updateRuleAt(value.mapping.custom_format_map, index, (row) => ({ ...row, name }))
            )
          }
        />
    </ArrBaseSection>
  );
}
