import { Alert, Button, Group, Stack, Textarea, Text } from "@mantine/core";
import { useEffect, useState } from "react";
import { getConfigYaml, saveConfigYaml, validateConfigYaml } from "../api/client";

export default function ConfigPanel() {
  const [yaml, setYaml] = useState<string>("");
  const [loaded, setLoaded] = useState(false);
  const [message, setMessage] = useState<{ color: string; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getConfigYaml()
      .then((text) => {
        setYaml(text);
        setLoaded(true);
      })
      .catch((error) => setMessage({ color: "red", text: `Load failed: ${String(error)}` }));
  }, []);

  const validate = async () => {
    setBusy(true);
    try {
      const result = await validateConfigYaml(yaml);
      setMessage(
        result.valid
          ? { color: "green", text: "Config is valid." }
          : { color: "red", text: `Invalid: ${result.error}` }
      );
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const result = await saveConfigYaml(yaml);
      setMessage({ color: "green", text: result.note ?? "Saved." });
    } catch (error) {
      setMessage({ color: "red", text: `Save failed: ${String(error)}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">
        Raw config.yaml. Validation runs the real config loader; saving keeps a .bak of the
        previous version. Restart the container to apply changes to the background loop.
      </Text>
      <Textarea
        value={yaml}
        onChange={(event) => setYaml(event.currentTarget.value)}
        autosize
        minRows={20}
        maxRows={40}
        styles={{ input: { fontFamily: "monospace", fontSize: 13 } }}
        disabled={!loaded}
      />
      <Group>
        <Button size="xs" variant="light" onClick={validate} loading={busy}>
          Validate
        </Button>
        <Button size="xs" onClick={save} loading={busy} disabled={!loaded}>
          Save
        </Button>
      </Group>
      {message && <Alert color={message.color}>{message.text}</Alert>}
    </Stack>
  );
}
