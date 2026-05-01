import { Button, Group, Modal, Stack, Text } from "@mantine/core";

type DeleteShadowConfirmModalProps = {
  opened: boolean;
  path: string | null;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
};

export default function DeleteShadowConfirmModal({
  opened,
  path,
  onCancel,
  onConfirm
}: DeleteShadowConfirmModalProps) {
  return (
    <Modal opened={opened} onClose={onCancel} title="Remove shadow folder" centered>
      <Stack>
        <Text size="sm">
          Are you sure you want to remove this shadow folder? This will delete the projected
          hardlinks but will NOT affect the original managed media files.
        </Text>
        <Text size="sm" fw={600} style={{ wordBreak: "break-all" }}>
          {path}
        </Text>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={onCancel}>
            Cancel
          </Button>
          <Button color="red" onClick={() => void onConfirm()}>
            Remove
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}