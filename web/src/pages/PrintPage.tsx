import type { Settings } from "../types";

interface Props {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onSave: () => void;
}

function toggleIn(list: string[], value: string, on: boolean): string[] {
  if (on) return Array.from(new Set([...list, value]));
  return list.filter((x) => x !== value);
}

const ACARS_TYPE_LABELS: Record<string, string> = {
  cpdlc: "CPDLC (ATC datalink)",
  telex: "Telex / company messages",
  inforeq: "Weather & ATIS replies",
};

const OFP_LABELS: Record<string, string> = {
  flight_plan: "Flight plan / OFP",
  takeoff_data: "Takeoff data",
  loadsheet_prelim: "Loadsheet (preliminary)",
  loadsheet_final: "Loadsheet (final)",
};

const WX_LABELS: Record<string, string> = {
  atis: "ATIS",
  metar: "METAR",
  taf: "TAF",
};

export function PrintPage({ settings, onChange, onSave }: Props) {
  return (
    <section className="space-y-4">
      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">
          Which ACARS messages to auto-print
        </h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Uncheck a type if you only want it in the message list, not on paper.
        </p>
        <div className="flex flex-wrap gap-4">
          {settings.printable_type_choices.map((t) => (
            <label key={t} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.printable_types.includes(t)}
                onChange={(e) =>
                  onChange({
                    printable_types: toggleIn(
                      settings.printable_types,
                      t,
                      e.target.checked,
                    ),
                  })
                }
              />
              {ACARS_TYPE_LABELS[t] || t}
            </label>
          ))}
        </div>
      </div>

      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">
          SimBrief OFP tickets
        </h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Which flight-plan sections to print when you fetch the OFP.
        </p>
        <div className="flex flex-wrap gap-4">
          {settings.ofp_ticket_choices.map((t) => (
            <label key={t} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.simbrief_ofp_tickets.includes(t)}
                onChange={(e) =>
                  onChange({
                    simbrief_ofp_tickets: toggleIn(
                      settings.simbrief_ofp_tickets,
                      t,
                      e.target.checked,
                    ),
                  })
                }
              />
              {OFP_LABELS[t] || t.replace(/_/g, " ")}
            </label>
          ))}
        </div>
      </div>

      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">
          Auto destination weather
        </h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Near arrival, print live destination weather automatically (real sources
          only).
        </p>
        <label className="mb-3 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={settings.wx_auto_enabled}
            onChange={(e) => onChange({ wx_auto_enabled: e.target.checked })}
          />
          Print destination weather when I get close
        </label>
        <div className="mb-3 grid max-w-xs gap-1">
          <span className="font-medium text-sm text-[var(--text)]">
            Distance to destination (NM)
          </span>
          <input
            type="number"
            min={10}
            max={500}
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-2 py-1.5 text-sm"
            value={settings.wx_auto_nm}
            placeholder="180"
            onChange={(e) => onChange({ wx_auto_nm: Number(e.target.value) })}
          />
          <span className="text-xs text-[var(--muted)]">
            Default 180 NM — starts printing once you are this close.
          </span>
        </div>
        <div className="flex flex-wrap gap-4">
          {settings.wx_auto_kind_choices.map((t) => (
            <label key={t} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.wx_auto_kinds.includes(t)}
                onChange={(e) =>
                  onChange({
                    wx_auto_kinds: toggleIn(
                      settings.wx_auto_kinds,
                      t,
                      e.target.checked,
                    ),
                  })
                }
              />
              {WX_LABELS[t] || t.toUpperCase()}
            </label>
          ))}
        </div>
      </div>

      <button
        type="button"
        className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
        onClick={onSave}
      >
        Save settings
      </button>
    </section>
  );
}
