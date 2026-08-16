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

export function uncShareName(raw: string): string {
  let text = (raw || "").trim();
  if (text.toLowerCase().startsWith("win32://")) {
    text = text.slice("win32://".length);
  }
  const unified = text.replace(/\//g, "\\");
  if (!unified.startsWith("\\\\")) return "";
  const parts = unified.split("\\").filter(Boolean);
  if (parts.length < 2) return "";
  return `\\\\${parts.join("\\")}`;
}

export function windowsSharePath(destination: string): string {
  return uncShareName(destination);
}

export function normalizePrinterDestination(raw: string): string {
  const text = (raw || "").trim();
  if (!text || text.toLowerCase() === "console" || text === "console (log only)") {
    return "console";
  }
  const share = uncShareName(text);
  if (share) return `win32://${share}`;
  if (text.toLowerCase().startsWith("win32://")) {
    const name = text.slice("win32://".length).trim();
    return name ? `win32://${name}` : "console";
  }
  return text;
}

export type PrinterInputMode = "list" | "ip" | "path";

export function inferPrinterInputMode(destination: string): PrinterInputMode {
  if (parseTcpPrinter(destination)) return "ip";
  if (windowsSharePath(destination)) return "path";
  return "list";
}

export function destinationFromPathDraft(
  draft: string,
  currentDestination: string,
  listFallback: string,
): string {
  const typed = (draft || "").trim();
  if (!typed) {
    return windowsSharePath(currentDestination) ? listFallback : currentDestination;
  }
  return normalizePrinterDestination(typed);
}

export function tcpPrinterDestination(host: string, port: number): string {
  const cleaned = (host || "").trim();
  if (!cleaned) return "";
  const safe =
    Number.isFinite(port) && port >= 1 && port <= 65535 ? port : DEFAULT_TCP_PORT;
  return `tcp://${cleaned}:${safe}`;
}
