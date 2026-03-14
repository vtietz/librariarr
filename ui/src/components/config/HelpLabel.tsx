import { ActionIcon, Group, Tooltip } from "@mantine/core";
import { IconHelpCircle } from "@tabler/icons-react";

type Props = {
  label: string;
  help: string;
};

export default function HelpLabel({ label, help }: Props) {
  return (
    <Group gap={4} wrap="nowrap">
      <span>{label}</span>
      <Tooltip label={help} multiline maw={320} withArrow>
        <ActionIcon
          variant="subtle"
          color="gray"
          size="xs"
          aria-label={`Help: ${label}`}
          onClick={(event) => event.preventDefault()}
        >
          <IconHelpCircle size={14} />
        </ActionIcon>
      </Tooltip>
    </Group>
  );
}