export const toOpenToolUrl = (configuredUrl: string, fallbackPort: number): string | null => {
  const trimmed = configuredUrl.trim();
  if (!trimmed) {
    return null;
  }

  const parseUrl = (value: string): URL | null => {
    try {
      return new URL(value);
    } catch {
      return null;
    }
  };

  const parsed = parseUrl(trimmed) ?? parseUrl(`http://${trimmed}`);
  if (!parsed) {
    return null;
  }

  const hostname = parsed.hostname.toLowerCase();
  const isIpv4 = /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname);
  const isIpv6 = hostname.includes(":");
  const isLoopback = hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
  const isLikelyInternalService =
    !isLoopback && !isIpv4 && !isIpv6 && hostname.length > 0 && !hostname.includes(".");

  if (isLikelyInternalService) {
    parsed.hostname = window.location.hostname;
    if (!parsed.port) {
      parsed.port = String(fallbackPort);
    }
  }

  if (parsed.pathname.toLowerCase().startsWith("/api")) {
    parsed.pathname = "/";
    parsed.search = "";
    parsed.hash = "";
  }

  return parsed.toString();
};
