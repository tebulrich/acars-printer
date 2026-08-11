import { useEffect, useRef } from "react";
import { formatMessageTime } from "../time";
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
  const detailScrollRef = useRef<HTMLDivElement>(null);
  const selectedBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const pane = detailScrollRef.current;
    if (pane) pane.scrollTop = 0;
  }, [detail?.id]);

  useEffect(() => {
    selectedBtnRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [selectedId]);

  return (
    <div
      className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] gap-3"
      style={{ gridTemplateRows: "minmax(0, 1fr)" }}
    >
      <section className="flex h-full min-h-0 flex-col overflow-hidden rounded border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Messages
          </h2>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-2 py-1 text-sm hover:bg-[var(--surface-alt)]"
            onClick={onRefresh}
          >
            Refresh
          </button>
        </div>
        <ul className="min-h-0 flex-1 overflow-auto">
          {messages.length === 0 && (
            <li className="px-3 py-6 text-sm text-[var(--muted)]">
              {running
                ? "Waiting for the aircraft to send ACARS…"
                : "No messages yet. Connect, then use ACARS in the sim."}
            </li>
          )}
          {messages.map((m) => (
            <li key={m.id}>
              <button
                type="button"
                ref={selectedId === m.id ? selectedBtnRef : undefined}
                className={`flex w-full flex-col gap-0.5 border-b border-[var(--border)] px-3 py-2 text-left hover:bg-[var(--bg)] ${
                  selectedId === m.id ? "bg-[var(--selected)]" : ""
                }`}
                onClick={() => onSelect(m.id)}
              >
                <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
                  <span>{formatMessageTime(m.received_at)}</span>
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

      <section className="flex h-full min-h-0 flex-col overflow-hidden rounded border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            Detail
          </h2>
          <div className="flex gap-2">
            {showDetail && detail && (
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-2 py-1 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
                onClick={onPrint}
              >
                Print
              </button>
            )}
            {autoPrint && detailOpened && (
              <button
                type="button"
                className="rounded border border-[var(--border)] bg-[var(--btn)] px-2 py-1 text-sm"
                onClick={onHide}
              >
                Hide
              </button>
            )}
          </div>
        </div>
        <div ref={detailScrollRef} className="min-h-0 flex-1 overflow-auto p-3">
          {!showDetail || !detail ? (
            <p className="text-sm text-[var(--muted)]">Select a message to inspect.</p>
          ) : (
            <>
              <div className="mb-2 text-sm font-semibold">
                {detail.message_type.toUpperCase()} · {detail.station || "—"}
              </div>
              <div className="mb-3 text-xs text-[var(--muted)]">
                {formatMessageTime(detail.received_at)} · {detail.direction.toUpperCase()} · {detail.callsign}
              </div>
              <pre className="whitespace-pre-wrap rounded bg-[var(--mono-bg)] p-3 font-mono text-[13px] leading-relaxed text-[var(--mono-fg)]">
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
