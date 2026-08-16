import type { ReactNode } from "react";
import type { Settings } from "../types";

interface Props {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onSave: () => void;
  onPrintOfp: () => void;
  onUnlockOfp: () => void;
  onCheckUpdates: () => void;
}

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
    <label className={`grid gap-1 text-sm ${className ?? ""}`.trim()}>
      <span className="font-medium text-[var(--text)]">{label}</span>
      {children}
      {hint ? <span className="text-xs text-[var(--muted)]">{hint}</span> : null}
    </label>
  );
}

export function SettingsPage({
  settings,
  onChange,
  onSave,
  onPrintOfp,
  onUnlockOfp,
  onCheckUpdates,
}: Props) {
  return (
    <section className="space-y-4">
      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Flight</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          When the aircraft may print, SimBrief lock, and app start behaviour.
        </p>
        <div className="grid max-w-xl items-start gap-3 sm:grid-cols-2">
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={settings.auto_print}
              onChange={(e) => onChange({ auto_print: e.target.checked })}
            />
            Print new messages automatically
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={settings.auto_connect}
              onChange={(e) => onChange({ auto_connect: e.target.checked })}
            />
            Connect automatically when the app starts
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={settings.check_updates}
              onChange={(e) => onChange({ check_updates: e.target.checked })}
            />
            Check for app updates
          </label>
          <Field
            className="sm:col-span-2"
            label="Sterile cockpit until (ft AGL)"
            hint="Below this, prints queue until sterile ends. Off prints anytime."
          >
            <select
              className={`${inputClass} max-w-xs`}
              value={settings.sterile_agl_ft}
              onChange={(e) => onChange({ sterile_agl_ft: Number(e.target.value) })}
            >
              {settings.sterile_agl_choices.map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? "Off" : `${n} ft`}
                </option>
              ))}
            </select>
          </Field>
          <label className="flex items-start gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={settings.print_when_powered}
              onChange={(e) => onChange({ print_when_powered: e.target.checked })}
            />
            <span>
              Only print when the aircraft is powered
              <span className="mt-0.5 block text-xs text-[var(--muted)]">
                X-Plane: engine, APU, or GPU selected — not bus volts.
              </span>
            </span>
          </label>
          <div className="grid gap-2 sm:col-span-2 sm:grid-cols-[minmax(0,1fr)_7.5rem] sm:items-end">
            <label className="grid gap-1 text-sm">
              <span className="font-medium text-[var(--text)]">X-Plane host</span>
              <input
                className={inputClass}
                value={settings.xplane_host}
                placeholder="127.0.0.1"
                title="Same PC: 127.0.0.1. Other PC: LAN IP. auto = localhost plus the X-Plane beacon."
                onChange={(e) => onChange({ xplane_host: e.target.value })}
              />
            </label>
            <label className="grid gap-1 text-sm">
              <span className="font-medium text-[var(--text)]">UDP port</span>
              <input
                type="number"
                min={1}
                max={65535}
                className={inputClass}
                value={settings.xplane_port}
                onChange={(e) => onChange({ xplane_port: Number(e.target.value) })}
              />
            </label>
            <p className="text-xs text-[var(--muted)] sm:col-span-2">
              Same PC: 127.0.0.1 · other PC: LAN IP · auto = beacon. XP12: Network →
              Accept incoming connections.
            </p>
          </div>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={settings.simbrief_enabled}
              onChange={(e) => onChange({ simbrief_enabled: e.target.checked })}
            />
            Enable SimBrief OFP printing
          </label>
          <Field label="SimBrief username or pilot ID">
            <input
              className={inputClass}
              value={settings.simbrief_user}
              onChange={(e) => onChange({ simbrief_user: e.target.value })}
            />
          </Field>
          <Field
            label="After-landing grace (seconds)"
            hint="How long the same OFP can still print after landing."
          >
            <input
              type="number"
              min={60}
              max={7200}
              className={inputClass}
              value={settings.simbrief_post_landing_grace_seconds}
              onChange={(e) =>
                onChange({
                  simbrief_post_landing_grace_seconds: Number(e.target.value),
                })
              }
            />
          </Field>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
            onClick={onSave}
          >
            Save settings
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={onPrintOfp}
          >
            Print OFP now
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={onUnlockOfp}
          >
            Unlock OFP
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={onCheckUpdates}
          >
            Check for updates now
          </button>
        </div>
        <p className="mt-2 text-xs text-[var(--muted)]">
          Unlock OFP is also under More, and on the OFP status chip in the header.
        </p>
      </div>
    </section>
  );
}
