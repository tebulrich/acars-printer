import type { ReactNode } from "react";
import type { Settings } from "../types";

interface Props {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onSave: () => void;
  onPrintOfp: () => void;
  onUnlockOfp: () => void;
  onCheckUpdates: () => void;
  onRotateToken: () => void;
  onOpenCompanion: () => void;
}

const inputClass =
  "rounded border border-[var(--border)] bg-white px-2 py-1.5 text-sm outline-none focus:border-[var(--accent)]";

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

export function SettingsPage({
  settings,
  onChange,
  onSave,
  onPrintOfp,
  onUnlockOfp,
  onCheckUpdates,
  onRotateToken,
  onOpenCompanion,
}: Props) {
  return (
    <section className="space-y-4">
      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">General</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Everyday options for printing, connection, and SimBrief.
        </p>
        <div className="grid max-w-xl gap-3 sm:grid-cols-2">
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
            label="Sterile cockpit until (ft AGL)"
            hint="Below this height, prints wait in a queue and release when sterile ends."
          >
            <select
              className={inputClass}
              value={settings.sterile_agl_ft}
              onChange={(e) => onChange({ sterile_agl_ft: Number(e.target.value) })}
            >
              {settings.sterile_agl_choices.map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? "Off (0)" : `${n} ft`}
                </option>
              ))}
            </select>
          </Field>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={settings.print_when_powered}
              onChange={(e) => onChange({ print_when_powered: e.target.checked })}
            />
            Only print when the aircraft is powered
          </label>
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
            label="After-landing grace period (seconds)"
            hint="How long after landing the same OFP can still print before unlock is needed."
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
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white hover:bg-[var(--accent-hover)]"
            onClick={onSave}
          >
            Save settings
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onPrintOfp}
          >
            Print OFP now
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onUnlockOfp}
          >
            Unlock OFP
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onCheckUpdates}
          >
            Check for updates now
          </button>
        </div>
      </div>

      <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Phone companion</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Open a simple page on your phone (same Wi‑Fi) to read printed ACARS
          messages. Optional: let the phone request weather, ATIS, telex, or PDC
          when the aircraft itself cannot.
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
              Starts a small local web page. Copy the phone URL below after saving.
              To let the phone request/send ACARS, use Network → Companion station
              mode.
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
        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white hover:bg-[var(--accent-hover)]"
            onClick={onSave}
          >
            Save settings
          </button>
          {settings.companion_url && (
            <button
              type="button"
              className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
              onClick={() => void navigator.clipboard.writeText(settings.companion_url)}
            >
              Copy URL
            </button>
          )}
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onRotateToken}
          >
            Rotate PIN
          </button>
          {settings.companion_url && (
            <button
              type="button"
              className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
              onClick={onOpenCompanion}
            >
              Open in browser
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
