import { useEffect, useRef, useState } from "react";

export function useUnmatchedDelta(params: {
  finishedAt: number | null | undefined;
  unmatchedMovies: number | undefined;
  unmatchedSeries: number | undefined;
}) {
  const { finishedAt, unmatchedMovies, unmatchedSeries } = params;
  const previousRef = useRef<{ finishedAt: number; movies: number | null; series: number | null } | null>(null);
  const [delta, setDelta] = useState<{ movies: number | null; series: number | null } | null>(null);

  useEffect(() => {
    if (typeof finishedAt !== "number") {
      return;
    }

    const current = {
      finishedAt,
      movies: typeof unmatchedMovies === "number" ? unmatchedMovies : null,
      series: typeof unmatchedSeries === "number" ? unmatchedSeries : null,
    };

    const previous = previousRef.current;
    if (previous && previous.finishedAt !== current.finishedAt) {
      setDelta({
        movies:
          previous.movies !== null && current.movies !== null
            ? current.movies - previous.movies
            : null,
        series:
          previous.series !== null && current.series !== null
            ? current.series - previous.series
            : null,
      });
    }
    previousRef.current = current;
  }, [finishedAt, unmatchedMovies, unmatchedSeries]);

  return delta;
}
