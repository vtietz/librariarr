export const EXCLUDE_PATH_SUGGESTIONS = [
  ".deletedByTMM/",
  ".trash/",
  ".librariarr/**",
  "specials/",
  "trailer/",
  "trailers/",
  "*-trailer.*",
  "* trailer.*",
  "extras/",
  "featurettes/",
  "bonus/",
  "sample/",
  "samples/"
];

export function normalizeExcludePaths(values: string[]): string[] {
  const normalized = values
    .map((value) => String(value).trim())
    .filter((value) => value.length > 0);
  return Array.from(new Set(normalized));
}
