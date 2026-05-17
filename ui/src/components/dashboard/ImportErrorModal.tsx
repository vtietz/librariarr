import { Button, Group, Modal, Stack, Text } from "@mantine/core";

type Props = {
  opened: boolean;
  path: string | null;
  errorMessage: string;
  busyImportPath: string | null;
  onClose: () => void;
  onRetry: () => void;
};

export default function ImportErrorModal({
  opened,
  path,
  errorMessage,
  busyImportPath,
  onClose,
  onRetry,
}: Props) {
  return (
    <Modal opened={opened} onClose={onClose} title="Import Error" centered>
      <Stack gap="sm">
        <Text size="sm" c="dimmed">
          {path}
        </Text>
        <Text size="sm">{errorMessage || "Import failed."}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Close
          </Button>
          <Button color="red" loading={path !== null && busyImportPath === path} onClick={onRetry}>
            Retry
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}
