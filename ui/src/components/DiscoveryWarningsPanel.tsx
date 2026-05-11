import { Stack, Title } from "@mantine/core";
import { useCallback, useEffect, useState } from "react";
import { getDiscoveryWarnings } from "../api/client";
import DiscoveryWarningsCard from "./dashboard/DiscoveryWarningsCard";

type DiscoveryWarnings = Awaited<ReturnType<typeof getDiscoveryWarnings>>;

export default function DiscoveryWarningsPanel() {
  const [discoveryWarnings, setDiscoveryWarnings] = useState<DiscoveryWarnings | null>(null);

  const refreshDiscoveryWarnings = useCallback(async () => {
    const payload = await getDiscoveryWarnings();
    setDiscoveryWarnings(payload);
  }, []);

  useEffect(() => {
    let active = true;
    let inFlight = false;

    const loadWarnings = async () => {
      if (inFlight) {
        return;
      }
      inFlight = true;
      try {
        const payload = await getDiscoveryWarnings();
        if (active) {
          setDiscoveryWarnings(payload);
        }
      } catch {
        // Keep last known snapshot to avoid flashing empty state on transient failures.
      } finally {
        inFlight = false;
      }
    };

    void loadWarnings();
    const interval = window.setInterval(() => {
      void loadWarnings();
    }, 7000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <Stack gap="md">
      <Title order={3}>Warnings</Title>
      <DiscoveryWarningsCard
        discoveryWarnings={discoveryWarnings}
        onRefreshWarnings={refreshDiscoveryWarnings}
      />
    </Stack>
  );
}
