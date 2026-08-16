const DEFAULT_TCP_PORT = 9100;

export function parseTcpPrinter(
  destination: string,
): { host: string; port: number } | null {
  const raw = (destination || "").trim();
  const match = raw.match(/^tcp:\/\/([^:/]+)(?::(\d+))?\/?$/i);
  if (!match) return null;
  const port = match[2] ? Number(match[2]) : DEFAULT_TCP_PORT;
  if (!Number.isFinite(port) || port < 1 || port > 65535) {
    return { host: match[1], port: DEFAULT_TCP_PORT };
  }
  return { host: match[1], port };
}

export function tcpPrinterDestination(host: string, port: number): string {
  const cleaned = (host || "").trim();
  if (!cleaned) return "";
  const safe =
    Number.isFinite(port) && port >= 1 && port <= 65535 ? port : DEFAULT_TCP_PORT;
  return `tcp://${cleaned}:${safe}`;
}
