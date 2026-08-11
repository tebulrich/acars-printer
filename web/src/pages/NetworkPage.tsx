import type { ReactNode } from "react";
import { useState } from "react";
import type { Settings } from "../types";

const inputClass =
  "rounded border border-[var(--border)] bg-white px-2 py-1.5 text-sm outline-none focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:bg-[var(--bg)] disabled:text-[var(--muted)]";

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1 text-sm">
      <span className="font-medium text-[var(--text)]">{label}</span>
      {children}
      {hint ? <span className="text-xs text-[var(--muted)]">{hint}</span> : null}
    </label>
  );
}

interface Props {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onSave: () => void;
  /** True when Connect/tap is watching (hook mode). */
  tapConnected?: boolean;
}

export function NetworkPage({
  settings,
  onChange,
  onSave,
  tapConnected = false,
}: Props) {
  const [logonDraft, setLogonDraft] = useState("");
  const stationOn = settings.companion_station_enabled;

  function toggleStation(checked: boolean) {
    if (checked && tapConnected) {
      const go = window.confirm(
        "Connect/tap is active (hook mode).\n\n" +
          "Station mode makes this PC own the Hoppie callsign. That usually " +
          "conflicts with the aircraft.\n\n" +
          "Only continue if the plane is NOT logged into Hoppie with this callsign.\n\n" +
          "Enable station mode anyway?",
      );
      if (!go) return;
    }
    onChange({ companion_station_enabled: checked });
  }

  return (
    <div className="space-y-4">
      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">
          Watching &amp; printing
        </h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Match the aircraft’s ACARS network. For normal tap/print the plane keeps
          its own logon — nothing else is required here.
        </p>
        <div className="grid max-w-xl gap-3">
          <Field label="ACARS network">
            <select
              className={inputClass}
              value={settings.acars_network}
              onChange={(e) => onChange({ acars_network: e.target.value })}
            >
              {settings.networks.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.label}
                </option>
              ))}
            </select>
          </Field>
          <Field
            label="Callsign filter"
            hint={
              "Optional print filter. Leave empty to print every flight — phone/station " +
              "then auto-follows SimBrief or the last ACARS callsign. Set one only to " +
              "force a specific callsign (also used as Hoppie “from” in station mode)."
            }
          >
            <input
              className={inputClass}
              value={settings.callsign}
              placeholder="Auto (SimBrief / last ACARS)"
              onChange={(e) => onChange({ callsign: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field
            label="Aircraft registration"
            hint="Optional tail number for the strip header (e.g. D-AILA)."
          >
            <input
              className={inputClass}
              value={settings.aircraft_registration}
              placeholder="e.g. D-AILA"
              onChange={(e) =>
                onChange({ aircraft_registration: e.target.value.toUpperCase() })
              }
            />
          </Field>
        </div>
      </section>

      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">
          Companion station mode
        </h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Optional offline mode. Lets this PC poll Hoppie as your callsign when
          MSFS is not holding it. While Connect/tap is active, the phone can
          already send weather / ATIS / telex / PDC through the aircraft’s live
          session — leave station mode off then.
        </p>
        <div className="grid max-w-xl gap-3">
          <label className="grid gap-1 text-sm">
            <span className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={settings.companion_station_enabled}
                onChange={(e) => toggleStation(e.target.checked)}
              />
              Enable station mode
            </span>
            <span className="pl-6 text-xs text-[var(--muted)]">
              This PC then polls (and can send) as your callsign without MSFS.
              On Save, Hoppie is checked — if the callsign is already in use
              (typical when Connect/tap + the aircraft hold it), station mode is
              turned back off automatically.
            </span>
          </label>

          <Field
            label="Hoppie logon code"
            hint={
              settings.has_hoppie_logon
                ? "Saved for station mode — leave blank to keep it. Connect/tap phone sends use the plane’s logon from the wire instead."
                : "Needed only for station mode (offline). Same code as hoppie.nl; stored encrypted. Connect/tap phone sends do not need this."
            }
          >
            <input
              className={inputClass}
              type="password"
              autoComplete="off"
              value={logonDraft}
              placeholder={
                settings.has_hoppie_logon ? "•••••••• (saved)" : "Enter logon code"
              }
              onChange={(e) => {
                setLogonDraft(e.target.value);
                onChange({ hoppie_logon: e.target.value });
              }}
            />
          </Field>
          {stationOn && !settings.callsign && !settings.has_hoppie_logon ? (
            <p className="text-xs text-[var(--muted)]">
              Callsign will auto-follow SimBrief or the last ACARS message when
              available.
            </p>
          ) : null}
        </div>
      </section>

      <button
        type="button"
        className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white hover:bg-[var(--accent-hover)]"
        onClick={() => {
          onSave();
          setLogonDraft("");
        }}
      >
        Save settings
      </button>
    </div>
  );
}
