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
