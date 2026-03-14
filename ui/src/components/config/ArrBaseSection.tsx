import { Button, Card, Checkbox, Group, Stack, Switch, Text, TextInput, Title } from "@mantine/core";
import type { ReactNode } from "react";
import HelpLabel from "./HelpLabel";

export type ToggleItem = {
  label: string;
  help: string;
  checked: boolean;
  kind?: "switch" | "checkbox";
  onChange: (checked: boolean) => void;
};

type Props = {
  title: string;
  toggles: ToggleItem[];
  urlLabel: string;
  urlHelp: string;
  urlValue: string;
  onUrlChange: (value: string) => void;
  apiKeyLabel: string;
  apiKeyHelp: string;
  apiKeyValue: string;
  onApiKeyChange: (value: string) => void;
  openLabel: string;
  openHref?: string;
  testLabel: string;
  onTest: () => Promise<void>;
  testing: boolean;
  testStatus: { ok: boolean; message: string } | null;
  children?: ReactNode;
};

export default function ArrBaseSection({
  title,
  toggles,
  urlLabel,
  urlHelp,
  urlValue,
  onUrlChange,
  apiKeyLabel,
  apiKeyHelp,
  apiKeyValue,
  onApiKeyChange,
  openLabel,
  openHref,
  testLabel,
  onTest,
  testing,
  testStatus,
  children
}: Props) {
  return (
    <Card withBorder>
      <Title order={4}>{title}</Title>
      <Stack mt="sm">
        <Group>
          {toggles.map((toggle, index) => {
            if (toggle.kind === "switch") {
              return (
                <Switch
                  key={`arr-toggle-${index}`}
                  label={<HelpLabel label={toggle.label} help={toggle.help} />}
                  checked={toggle.checked}
                  onChange={(event) => toggle.onChange(event.currentTarget.checked)}
                />
              );
            }
            return (
              <Checkbox
                key={`arr-toggle-${index}`}
                label={<HelpLabel label={toggle.label} help={toggle.help} />}
                checked={toggle.checked}
                onChange={(event) => toggle.onChange(event.currentTarget.checked)}
              />
            );
          })}
        </Group>

        <TextInput
          label={<HelpLabel label={urlLabel} help={urlHelp} />}
          value={urlValue}
          onChange={(event) => onUrlChange(event.currentTarget.value)}
        />
        <TextInput
          label={<HelpLabel label={apiKeyLabel} help={apiKeyHelp} />}
          value={apiKeyValue}
          onChange={(event) => onApiKeyChange(event.currentTarget.value)}
        />

        <Group>
          <Button
            component="a"
            variant="default"
            href={openHref}
            target="_blank"
            rel="noopener noreferrer"
            disabled={!openHref}
          >
            {openLabel}
          </Button>
          <Button variant="light" onClick={() => void onTest()} loading={testing}>
            {testLabel}
          </Button>
          {testStatus ? <Text size="sm" c={testStatus.ok ? "green" : "red"}>{testStatus.message}</Text> : null}
        </Group>

        {children}
      </Stack>
    </Card>
  );
}
