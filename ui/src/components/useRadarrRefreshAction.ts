import { useCallback } from "react";
import { refreshRadarrMovie } from "../api/client";

type Params = {
  setRefreshingMovieId: (movieId: number | null) => void;
  setLoadError: (message: string | null) => void;
  loadMappedDirectories: () => Promise<void>;
};

export function useRadarrRefreshAction({
  setRefreshingMovieId,
  setLoadError,
  loadMappedDirectories
}: Params) {
  return useCallback(
    async (movieId: number) => {
      setRefreshingMovieId(movieId);
      setLoadError(null);
      try {
        await refreshRadarrMovie(movieId);
        await loadMappedDirectories();
      } catch (error) {
        setLoadError(
          error instanceof Error
            ? `Radarr refresh failed: ${error.message}`
            : "Radarr refresh failed unexpectedly."
        );
      } finally {
        setRefreshingMovieId(null);
      }
    },
    [loadMappedDirectories, setLoadError, setRefreshingMovieId]
  );
}
