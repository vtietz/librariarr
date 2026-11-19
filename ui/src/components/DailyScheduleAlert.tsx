import { Alert, Stack, Text } from "@mantine/core";
import type { ScheduleInfo } from "../api/client";

const formatTime = (epochSeconds: number | null | undefined): string =>
  epochSeconds ? new Date(epochSeconds * 1000).toLocaleString() : "–";

export function DailyScheduleAlert({ schedule }: { schedule: ScheduleInfo }) {
  const failed = schedule.last_result === "failed";
  const color = failed ? "red" : schedule.missed_slot ? "yellow" : "gray";
  return (
    <Alert color={color} title={`Daily full pass at ${schedule.time} (${schedule.timezone})`}>
      <Stack gap={2}>
        <Text size="sm">Next run: {formatTime(schedule.next_run_at)}</Text>
        <Text size="sm">
          Last success: {schedule.last_success_slot ?? "never"}
          {schedule.last_success_at ? ` (${formatTime(schedule.last_success_at)})` : ""}
        </Text>
        {failed && (
          <Text size="sm">
            Last attempt ({schedule.last_attempt_slot}) failed
            {schedule.consecutive_failures > 1 ? ` ${schedule.consecutive_failures}× in a row` : ""}
            : {schedule.last_error}.{" "}
            {schedule.retry_at
              ? `Retrying at ${formatTime(schedule.retry_at)}.`
              : "Next attempt at the next scheduled slot."}
          </Text>
        )}
        {schedule.missed_slot && (
          <Text size="sm">
            The {schedule.missed_slot} run was missed (LibrariArr was not running or the
            previous attempt failed); it is not caught up on startup.
          </Text>
        )}
      </Stack>
    </Alert>
  );
}
