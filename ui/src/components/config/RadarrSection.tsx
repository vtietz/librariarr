import { Group, NumberInput } from "@mantine/core";
import { useState } from "react";
import { testRadarrConnection } from "../../api/client";
import type { ConfigModel } from "../../types/config";
import { toOpenToolUrl } from "../../utils/toolUrl";
import ArrBaseSection from "./ArrBaseSection";
import { buildRadarrToggles } from "./arrToggleBuilders";
import { parseNullableNumber } from "./numberParsers";
import RuleEditor from "./RuleEditor";
import { addRule, removeRuleAt, updateRuleAt } from "./ruleListState";

type Props = {
  value: ConfigModel["radarr"];
  onChange: (next: ConfigModel["radarr"]) => void;
};

export default function RadarrSection({ value, onChange }: Props) {
  const [testing, setTesting] = useState(false);
  const [testStatus, setTestStatus] = useState<{ ok: boolean; message: string } | null>(null);

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
        <NumberInput
          label="Auto-add Quality Profile ID"
          value={value.auto_add_quality_profile_id ?? undefined}
          min={1}
          allowDecimal={false}
          onChange={(fieldValue) => setField("auto_add_quality_profile_id", parseNullableNumber(fieldValue))}
        />
      </Group>

        <RuleEditor
          title="Radarr Quality Map"
          idLabel="Target ID"
          rows={value.mapping.quality_map}
          keyPrefix="radarr-quality"
          readId={(row) => row.target_id}
          onAdd={() =>
            setMappingField(
              "quality_map",
              addRule(value.mapping.quality_map, () => ({ match: [], target_id: 1, name: "" }))
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
          rows={value.mapping.custom_format_map}
          keyPrefix="radarr-format"
          readId={(row) => row.format_id}
          onAdd={() =>
            setMappingField(
              "custom_format_map",
              addRule(value.mapping.custom_format_map, () => ({ match: [], format_id: 1, name: "" }))
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
