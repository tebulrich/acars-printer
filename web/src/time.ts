/** Message list/detail stamp: ``11.08.2026 - 15:53:17`` (UTC). */
export function formatMessageTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const raw = iso.trim();
  if (!raw) return "—";
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw);
  const d = new Date(hasZone ? raw : `${raw}Z`);
  if (Number.isNaN(d.getTime())) return raw;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}` +
    ` - ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
  );
}
