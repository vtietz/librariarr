export function formatAge(timestamp: number | null | undefined): string {
  if (typeof timestamp !== "number") {
    return "-";
  }
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m ago`;
  }
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

export function formatTaskDuration(task: {
  duration_seconds?: number | null;
  started_at?: number | null;
}): string {
  if (typeof task.duration_seconds === "number") {
    return `${task.duration_seconds.toFixed(1)}s`;
  }
  if (typeof task.started_at === "number") {
    const now = Date.now() / 1000;
    return `${Math.max(0, now - task.started_at).toFixed(1)}s`;
  }
  return "-";
}

export function formatTaskQueuedAt(task: {
  queued_at?: number | null;
  next_run_at?: number | null;
}): string {
  if (typeof task.queued_at === "number") {
    return formatAge(task.queued_at);
  }
  if (typeof task.next_run_at === "number") {
    const dueIn = Math.max(0, Math.round(task.next_run_at - Date.now() / 1000));
    return `in ${dueIn}s`;
  }
  return "-";
}

export function badgeForTask(status: string): string {
  if (status === "running") {
    return "blue";
  }
  if (status === "queued") {
    return "yellow";
  }
  if (status === "error") {
    return "red";
  }
  return "gray";
}

export function formatCoverage(matched: number | undefined, unmatched: number | undefined): string {
  const matchedValue = typeof matched === "number" ? matched : 0;
  const unmatchedValue = typeof unmatched === "number" ? unmatched : 0;
  const total = matchedValue + unmatchedValue;
  if (total <= 0) {
    return "n/a";
  }
  const pct = Math.round((matchedValue / total) * 100);
  return `${pct}% (${matchedValue}/${total})`;
}

export function formatSigned(value: number | null): string {
  if (value === null) {
    return "n/a";
  }
  if (value > 0) {
    return `+${value}`;
  }
  return `${value}`;
}
