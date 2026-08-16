import type { ReactNode } from "react";
import { useState } from "react";
import type { Settings } from "../types";

const inputClass = "inp text-sm";

function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string;
  hint?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label className={`grid gap-1 self-start text-sm ${className ?? ""}`.trim()}>
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
          "Station mode logs this PC onto Hoppie with your callsign. That " +
          "usually conflicts with the aircraft.\n\n" +
          "Enable only if the plane is not on Hoppie.\n\n" +
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
          Match the aircraft ACARS network. The plane keeps its own logon.
        </p>
        <div className="grid max-w-xl items-start gap-3 sm:grid-cols-2">
          <Field className="sm:col-span-2" label="ACARS network">
            <select
              className={`${inputClass} max-w-xs`}
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
          <Field label="Callsign filter" hint="Empty = print every flight.">
            <input
              className={inputClass}
              value={settings.callsign}
              placeholder="Auto"
              onChange={(e) => onChange({ callsign: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field label="Aircraft registration" hint="Optional. ACARS header only.">
            <input
              className={inputClass}
              value={settings.aircraft_registration}
              placeholder="D-AILA"
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
          Off unless the aircraft is not on Hoppie and the phone still needs to send.
        </p>
        <div className="grid max-w-xl items-start gap-3">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={settings.companion_station_enabled}
              onChange={(e) => toggleStation(e.target.checked)}
            />
            <span>
              Enable station mode
              <span className="mt-0.5 block text-xs text-[var(--muted)]">
                This PC uses your callsign on Hoppie. Turns off if the aircraft
                already holds it.
              </span>
            </span>
          </label>
          <Field
            label="Hoppie logon code"
            hint={
              settings.has_hoppie_logon
                ? "Saved. Leave blank to keep it."
                : "Station mode only. Stored encrypted."
            }
          >
            <input
              className={`${inputClass} max-w-xs`}
              type="password"
              autoComplete="off"
              value={logonDraft}
              placeholder={
                settings.has_hoppie_logon ? "•••••••• (saved)" : "Logon code"
              }
              onChange={(e) => {
                setLogonDraft(e.target.value);
                onChange({ hoppie_logon: e.target.value });
              }}
            />
          </Field>
          {stationOn && !settings.callsign && !settings.has_hoppie_logon ? (
            <p className="text-xs text-[var(--muted)]">
              Callsign follows SimBrief or the last ACARS message.
            </p>
          ) : null}
        </div>
      </section>

      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Phone companion</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Same Wi-Fi inbox. Anyone on this LAN can open the URL.
        </p>
        <div className="grid max-w-xl items-start gap-3 sm:grid-cols-[1fr_7.5rem]">
          <label className="flex items-start gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={settings.companion_enabled}
              onChange={(e) => onChange({ companion_enabled: e.target.checked })}
            />
            Let my phone show the message inbox
          </label>
          <Field
            className="sm:col-span-2 sm:max-w-[7.5rem]"
            label="Port"
            hint="Default 8765."
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
            <div className="rounded border border-[var(--border)] bg-[var(--bg)] p-3 text-sm sm:col-span-2">
              <div className="mb-1 text-xs uppercase tracking-wide text-[var(--muted)]">
                Phone URL
              </div>
              <code className="break-all text-[13px]">{settings.companion_url}</code>
              {settings.companion_qr_png ? (
                <img
                  alt="QR code for the phone companion"
                  className="mt-3 h-36 w-36 bg-white p-1"
                  src={`data:image/png;base64,${settings.companion_qr_png}`}
                />
              ) : null}
              <p className="mt-2 text-xs text-[var(--muted)]">
                Also printed on the flight-plan strip. Bookmark it — no PIN.
              </p>
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
