import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MappedDirectory } from "./DirectoryMapperRows";

export type MapperStatusFilterValue =
  | "arr_ok"
  | "not_in_arr"
  | "missing_target"
  | "arr_offline"
  | "missing_virtual"
  | "other";

export const MAPPER_STATUS_FILTER_OPTIONS: Array<{
  value: MapperStatusFilterValue;
  label: string;
}> = [
  { value: "arr_ok", label: "A Arr ok" },
  { value: "not_in_arr", label: "N Not in Arr" },
  { value: "missing_target", label: "M Missing target" },
  { value: "arr_offline", label: "Off Arr offline" },
  { value: "missing_virtual", label: "V Missing virtual" },
  { value: "other", label: "Other" }
];

const PAGE_SIZE = 200;

function classifyArrState(arrState: string | undefined): MapperStatusFilterValue {
  switch (arrState) {
    case "ok":
    case "title_path_mismatch":
      return "arr_ok";
    case "missing_in_arr":
      return "not_in_arr";
    case "missing_on_disk":
      return "missing_target";
    case "arr_unreachable":
      return "arr_offline";
    case "missing_virtual_path":
      return "missing_virtual";
    default:
      return "other";
  }
}

export function useMapperRowsView(mappedDirectories: MappedDirectory[]) {
  const [activeStatusFilters, setActiveStatusFilters] = useState<MapperStatusFilterValue[]>([]);
  const [visibleRowCount, setVisibleRowCount] = useState(PAGE_SIZE);
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  const filteredDirectories = useMemo(() => {
    if (activeStatusFilters.length === 0) {
      return mappedDirectories;
    }
    const allowed = new Set(activeStatusFilters);
    return mappedDirectories.filter((item) => allowed.has(classifyArrState(item.arr_state)));
  }, [activeStatusFilters, mappedDirectories]);

  const visibleDirectories = useMemo(
    () => filteredDirectories.slice(0, visibleRowCount),
    [filteredDirectories, visibleRowCount]
  );

  const hasMoreRows = visibleRowCount < filteredDirectories.length;

  useEffect(() => {
    setVisibleRowCount(PAGE_SIZE);
  }, [mappedDirectories, activeStatusFilters]);

  useEffect(() => {
    if (!hasMoreRows) {
      return;
    }
    const sentinel = loadMoreRef.current;
    if (!sentinel) {
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisibleRowCount((previous) => Math.min(previous + PAGE_SIZE, filteredDirectories.length));
        }
      },
      {
        root: null,
        rootMargin: "220px 0px 220px 0px",
        threshold: 0
      }
    );

    observer.observe(sentinel);
    return () => {
      observer.disconnect();
    };
  }, [filteredDirectories.length, hasMoreRows]);

  const toggleStatusFilter = useCallback((value: MapperStatusFilterValue) => {
    setActiveStatusFilters((previous) =>
      previous.includes(value)
        ? previous.filter((item) => item !== value)
        : [...previous, value]
    );
  }, []);

  const clearStatusFilters = useCallback(() => {
    setActiveStatusFilters([]);
  }, []);

  return {
    activeStatusFilters,
    filteredDirectories,
    visibleDirectories,
    hasMoreRows,
    loadMoreRef,
    toggleStatusFilter,
    clearStatusFilters
  };
}
