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

export function formatElapsed(startTimestamp: number): string {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - startTimestamp));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainSec = seconds % 60;
  return `${minutes}m ${remainSec}s`;
}

export function formatDurationSeconds(durationSeconds: number | null | undefined): string {
  if (typeof durationSeconds !== "number" || !Number.isFinite(durationSeconds)) {
    return "0s";
  }

  const totalSeconds = Math.max(0, Math.round(durationSeconds));
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const parts: string[] = [];

  if (hours > 0) {
    parts.push(`${hours}h`);
  }
  if (minutes > 0 || hours > 0) {
    parts.push(`${minutes}m`);
  }
  if (seconds > 0 || parts.length === 0) {
    parts.push(`${seconds}s`);
  }

  return parts.join(" ");
}
