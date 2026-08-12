import type { ReactNode } from "react";
import { useState } from "react";
import type { Settings } from "../types";

const inputClass = "inp text-sm";

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
  onOpenCompanion: () => void;
}

export function NetworkPage({
  settings,
  onChange,
  onSave,
  tapConnected = false,
  onOpenCompanion,
}: Props) {
  const [logonDraft, setLogonDraft] = useState("");
  const stationOn = settings.companion_station_enabled;

  function toggleStation(checked: boolean) {
    if (checked && tapConnected) {
      const go = window.confirm(
        "Connect is already running.\n\n" +
          "Station mode makes this PC use your callsign on Hoppie. That usually " +
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
          Match the aircraft ACARS network. For normal printing the plane keeps
          its own Hoppie logon. Nothing else is required here.
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
              "Optional. Leave empty to print every flight. The phone then follows " +
              "SimBrief or the last ACARS callsign. Set a callsign only if you want " +
              "to force one (also used in station mode)."
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
            hint={
              "Optional. Printed on ACARS strip headers. If set, it is used instead " +
              "of the SimBrief tail for auto weather strips. Leave empty to omit the " +
              "tail on ACARS headers — SimBrief OFP tickets still show the OFP registration."
            }
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
          Leave this off in normal use. After you press Connect and the plane is
          on Hoppie, the phone can already send weather, ATIS, telex, and PDC
          using the aircraft. Turn station mode on only when the plane is not
          logged into Hoppie and you still want the phone to send as your
          callsign from this PC.
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
              This PC then uses your callsign on Hoppie without the sim. When you
              save, we check Hoppie. If the callsign is already taken by the
              aircraft, station mode turns off by itself.
            </span>
          </label>

          <Field
            label="Hoppie logon code"
            hint={
              settings.has_hoppie_logon
                ? "Saved for station mode. Leave blank to keep it. Phone sends while Connect is active use the plane instead."
                : "Only needed for station mode. Same code as hoppie.nl; stored encrypted. Not required when the phone sends through Connect and the plane."
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

      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Phone companion</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Open a page on your phone (same Wi-Fi) to read the inbox, reprint, and
          reply WILCO. Anyone on your home network can open the URL.
        </p>
        <div className="grid max-w-xl gap-3">
          <label className="grid gap-1 text-sm">
            <span className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={settings.companion_enabled}
                onChange={(e) => onChange({ companion_enabled: e.target.checked })}
              />
              Let my phone show the message inbox
            </span>
            <span className="pl-6 text-xs text-[var(--muted)]">
              Starts a local page on your Wi-Fi. Copy the URL after saving.
              Phone sends need Connect (after one Hoppie message) or station
              mode above.
            </span>
          </label>
          <Field
            label="Port number"
            hint="Usually leave at 8765 unless something else on your PC already uses it."
          >
            <input
              type="number"
              min={1024}
              max={65535}
              className={inputClass}
              value={settings.companion_port}
              onChange={(e) => onChange({ companion_port: Number(e.target.value) })}
            />
          </Field>
          {settings.companion_enabled && settings.companion_url && (
            <div className="rounded border border-[var(--border)] bg-[var(--bg)] p-3 text-sm">
              <div className="mb-1 text-xs uppercase tracking-wide text-[var(--muted)]">
                Phone URL
              </div>
              <code className="break-all text-[13px]">{settings.companion_url}</code>
            </div>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {settings.companion_url && (
            <button
              type="button"
              className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
              onClick={() => void navigator.clipboard.writeText(settings.companion_url)}
            >
              Copy URL
            </button>
          )}
          {settings.companion_url && (
            <button
              type="button"
              className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
              onClick={onOpenCompanion}
            >
              Open in browser
            </button>
          )}
        </div>
      </section>

      <button
        type="button"
        className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
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
