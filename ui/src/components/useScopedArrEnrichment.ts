import { useEffect, useRef } from "react";
import { getMappedDirectories } from "../api/client";
import type { MappedDirectory } from "./DirectoryMapperRows";
import { mergeMappedDirectoriesByVirtualPath } from "./directoryMapperLoadUtils";

type UseScopedArrEnrichmentParams = {
  candidates: MappedDirectory[];
  search: string;
  mappedRootFilter: string;
  mappedLoadVersionRef: React.MutableRefObject<number>;
  setMappedDirectories: React.Dispatch<React.SetStateAction<MappedDirectory[]>>;
  setCacheBuilding: React.Dispatch<React.SetStateAction<boolean>>;
  setCacheReady: React.Dispatch<React.SetStateAction<boolean>>;
  setCacheUpdatedAtMs: React.Dispatch<React.SetStateAction<number | null>>;
  setCacheEntriesTotal: React.Dispatch<React.SetStateAction<number>>;
  setArrEnrichmentLoading: React.Dispatch<React.SetStateAction<boolean>>;
};

export function useScopedArrEnrichment({
  candidates,
  search,
  mappedRootFilter,
  mappedLoadVersionRef,
  setMappedDirectories,
  setCacheBuilding,
  setCacheReady,
  setCacheUpdatedAtMs,
  setCacheEntriesTotal,
  setArrEnrichmentLoading
}: UseScopedArrEnrichmentParams) {
  const arrEnrichedPathsRef = useRef<Set<string>>(new Set());
  const arrInFlightPathsRef = useRef<Set<string>>(new Set());
  const arrEnrichmentLoadVersionRef = useRef(0);
  const arrRootFallbackKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const currentLoadVersion = mappedLoadVersionRef.current;
    if (arrEnrichmentLoadVersionRef.current !== currentLoadVersion) {
      arrEnrichmentLoadVersionRef.current = currentLoadVersion;
      arrEnrichedPathsRef.current = new Set();
      arrInFlightPathsRef.current = new Set();
      arrRootFallbackKeyRef.current = null;
    }

    const pendingVirtualPaths = Array.from(
      new Set(
        candidates
          .map((item) => item.virtual_path.trim())
          .filter((value) => value.length > 0)
      )
    ).filter(
      (value) => !arrEnrichedPathsRef.current.has(value) && !arrInFlightPathsRef.current.has(value)
    );

    if (pendingVirtualPaths.length === 0) {
      const fallbackKey = `${mappedRootFilter}::${search.trim()}`;
      const shouldRunRootFallback =
        candidates.length === 0 &&
        mappedRootFilter !== "all" &&
        arrRootFallbackKeyRef.current !== fallbackKey;

      if (!shouldRunRootFallback) {
        if (arrInFlightPathsRef.current.size === 0) {
          setArrEnrichmentLoading(false);
        }
        return;
      }

      setArrEnrichmentLoading(true);
      arrRootFallbackKeyRef.current = fallbackKey;

      const searchParam = search.trim();
      const shadowRootParam = mappedRootFilter;

      void (async () => {
        try {
          const result = await getMappedDirectories({
            search: searchParam || undefined,
            shadowRoot: shadowRootParam,
            limit: 5000,
            includeArrState: true,
            timeoutMs: 45000
          });

          if (mappedLoadVersionRef.current !== currentLoadVersion) {
            return;
          }

          setMappedDirectories((previous) =>
            mergeMappedDirectoriesByVirtualPath(previous, result.items as MappedDirectory[])
          );
          setCacheBuilding(result.cache?.building ?? false);
          setCacheReady(result.cache?.ready ?? false);
          setCacheUpdatedAtMs(result.cache?.updated_at_ms ?? null);
          setCacheEntriesTotal(result.cache?.entries_total ?? 0);
        } catch {
          /* keep base snapshot when root fallback enrichment fails */
        } finally {
          if (arrInFlightPathsRef.current.size === 0) {
            setArrEnrichmentLoading(false);
          }
        }
      })();

      return;
    }

    setArrEnrichmentLoading(true);

    for (const virtualPath of pendingVirtualPaths) {
      arrInFlightPathsRef.current.add(virtualPath);
    }

    const searchParam = search.trim();
    const shadowRootParam = mappedRootFilter !== "all" ? mappedRootFilter : undefined;

    void (async () => {
      let success = false;
      try {
        const result = await getMappedDirectories({
          search: searchParam || undefined,
          shadowRoot: shadowRootParam,
          limit: 5000,
          includeArrState: true,
          arrVirtualPaths: pendingVirtualPaths,
          timeoutMs: 45000
        });

        if (mappedLoadVersionRef.current !== currentLoadVersion) {
          return;
        }

        setMappedDirectories((previous) =>
          mergeMappedDirectoriesByVirtualPath(previous, result.items as MappedDirectory[])
        );
        setCacheBuilding(result.cache?.building ?? false);
        setCacheReady(result.cache?.ready ?? false);
        setCacheUpdatedAtMs(result.cache?.updated_at_ms ?? null);
        setCacheEntriesTotal(result.cache?.entries_total ?? 0);
        success = true;
      } catch {
        /* keep base snapshot when scoped Arr enrichment fails */
      } finally {
        for (const virtualPath of pendingVirtualPaths) {
          arrInFlightPathsRef.current.delete(virtualPath);
          if (success) {
            arrEnrichedPathsRef.current.add(virtualPath);
          }
        }
        if (arrInFlightPathsRef.current.size === 0) {
          setArrEnrichmentLoading(false);
        }
      }
    })();
  }, [
    candidates,
    mappedRootFilter,
    mappedLoadVersionRef,
    search,
    setCacheBuilding,
    setCacheEntriesTotal,
    setCacheReady,
    setCacheUpdatedAtMs,
    setArrEnrichmentLoading,
    setMappedDirectories
  ]);
}
