import type { MessageRow, Settings } from "../types";

interface Props {
  messages: MessageRow[];
  selectedId: number | null;
  detail: MessageRow | null;
  autoPrint: boolean;
  detailOpened: boolean;
  onSelect: (id: number) => void;
  onRefresh: () => void;
  onPrint: () => void;
  onHide: () => void;
  running: boolean;
}

export function MessagesPage({
  messages,
  selectedId,
  detail,
  autoPrint,
  detailOpened,
  onSelect,
  onRefresh,
  onPrint,
  onHide,
  running,
}: Props) {
  const showDetail = !autoPrint || detailOpened;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <section className="flex min-h-0 flex-col rounded border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Messages
          </h2>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-2 py-1 text-sm hover:bg-[var(--bg)]"
            onClick={onRefresh}
          >
            Refresh
          </button>
        </div>
        <ul className="min-h-0 flex-1 overflow-auto">
          {messages.length === 0 && (
            <li className="px-3 py-6 text-sm text-[var(--muted)]">
              {running
                ? "Connected — waiting for ACARS traffic…"
                : "No messages yet. Connect to start watching."}
            </li>
          )}
          {messages.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                className={`flex w-full flex-col gap-0.5 border-b border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--bg)] ${
                  selectedId === m.id ? "bg-[#eaf1fb]" : ""
                }`}
                onClick={() => onSelect(m.id)}
              >
                <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span>{m.received_at.slice(11, 16)}Z</span>
                  <span>{m.direction.toUpperCase()}</span>
                  <span>{m.station || "—"}</span>
                  <span className="ml-auto font-medium">{m.print_mark}</span>
                </div>
                <div className="truncate text-sm">
                  <span className="font-medium uppercase">{m.message_type}</span>{" "}
                  <span className="text-[var(--muted)]">{m.preview}</span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex min-h-0 flex-col rounded border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Detail
          </h2>
          <div className="flex gap-2">
            {showDetail && detail && (
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-2 py-1 text-sm text-white hover:bg-[var(--accent-hover)]"
                onClick={onPrint}
              >
                Print
              </button>
            )}
            {autoPrint && detailOpened && (
              <button
                type="button"
                className="rounded border border-[var(--border)] bg-white px-2 py-1 text-sm"
                onClick={onHide}
              >
                Hide
              </button>
            )}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-3">
          {!showDetail || !detail ? (
            <p className="text-sm text-[var(--muted)]">Select a message to inspect.</p>
          ) : (
            <>
              <div className="mb-2 text-sm font-semibold">
                {detail.message_type.toUpperCase()} · {detail.station || "—"}
              </div>
              <div className="mb-3 text-xs text-[var(--muted)]">
                {detail.received_at} · {detail.direction.toUpperCase()} · {detail.callsign}
              </div>
              <pre className="whitespace-pre-wrap rounded bg-[#0f1720] p-3 font-mono text-[13px] leading-relaxed text-[#d7e0ea]">
                {detail.normalized_body || ""}
              </pre>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

export type { Settings };
