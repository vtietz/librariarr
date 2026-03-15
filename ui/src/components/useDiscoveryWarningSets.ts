import { useMemo } from "react";
import type { DiscoveryWarningsResponse } from "../api/client";

export function useDiscoveryWarningSets(
  discoveryWarnings: DiscoveryWarningsResponse | null
): {
  duplicatePrimaryPaths: Set<string>;
  excludedByDuplicate: Map<string, number>;
  duplicatePathSet: Set<string>;
  excludedPathSet: Set<string>;
} {
  const duplicatePrimaryPaths = useMemo(() => {
    const paths = new Set<string>();
    for (const item of discoveryWarnings?.duplicate_movie_candidates ?? []) {
      paths.add(item.primary_path);
    }
    return paths;
  }, [discoveryWarnings]);

  const excludedByDuplicate = useMemo(() => {
    const byPrimary = new Map<string, number>();
    for (const item of discoveryWarnings?.duplicate_movie_candidates ?? []) {
      if (!item.contains_excluded) {
        continue;
      }
      byPrimary.set(item.primary_path, item.duplicate_paths.length);
    }
    return byPrimary;
  }, [discoveryWarnings]);

  const duplicatePathSet = useMemo(() => {
    const paths = new Set<string>();
    for (const item of discoveryWarnings?.duplicate_movie_candidates ?? []) {
      paths.add(item.primary_path);
      for (const duplicatePath of item.duplicate_paths) {
        paths.add(duplicatePath);
      }
    }
    return paths;
  }, [discoveryWarnings]);

  const excludedPathSet = useMemo(() => {
    const paths = new Set<string>();
    for (const item of discoveryWarnings?.excluded_movie_candidates ?? []) {
      if (item?.path) {
        paths.add(item.path);
      }
    }
    return paths;
  }, [discoveryWarnings]);

  return {
    duplicatePrimaryPaths,
    excludedByDuplicate,
    duplicatePathSet,
    excludedPathSet,
  };
}