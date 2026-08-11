import type { ReactNode } from "react";
import type { PrintProfile, PrinterChoice, Settings } from "../types";

interface Props {
  settings: Settings;
  printers: PrinterChoice[];
  profiles: PrintProfile[];
  onChange: (patch: Partial<Settings>) => void;
  onApplyProfile: (id: string) => void;
  onSaveProfile: () => void;
  onDeleteProfile: () => void;
  onSave: () => void;
  onSaveAndTest: () => void;
  onReset: () => void;
  profileId: string;
  onProfileId: (id: string) => void;
}

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

function mmHint(px: number): string {
  const mm = Math.round((px / 8) * 10) / 10;
  return `About ${mm} mm tall on a typical POS-80 (8 dots ≈ 1 mm). Lower if text looks too big.`;
}

const inputClass =
  "rounded border border-[var(--border)] bg-white px-2 py-1.5 text-sm outline-none focus:border-[var(--accent)]";

export function FormatPage({
  settings,
  printers,
  profiles,
  onChange,
  onApplyProfile,
  onSaveProfile,
  onDeleteProfile,
  onSave,
  onSaveAndTest,
  onReset,
  profileId,
  onProfileId,
}: Props) {
  const bitmap = settings.print_render_mode === "bitmap";

  return (
    <div className="space-y-4">
      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Print format</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Pick a profile or tweak the look, then use Save and test print.
        </p>
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <Field label="Saved profile">
            <select
              className={inputClass}
              value={profileId}
              onChange={(e) => onProfileId(e.target.value)}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={() => onApplyProfile(profileId)}
          >
            Apply profile
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onSaveProfile}
          >
            Save as…
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onDeleteProfile}
          >
            Delete profile
          </button>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Printer">
            <select
              className={inputClass}
              value={settings.printer_destination}
              onChange={(e) => onChange({ printer_destination: e.target.value })}
            >
              {printers.map((p) => (
                <option key={p.destination} value={p.destination}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Paper width">
            <select
              className={inputClass}
              value={settings.paper_width}
              onChange={(e) => onChange({ paper_width: e.target.value })}
            >
              <option value="80">80 mm (standard)</option>
              <option value="58">58 mm (narrow)</option>
            </select>
          </Field>
          <Field
            label="Cut / tear assist"
            hint="Feeds paper to the tear bar, then cuts if the printer can."
          >
            <select
              className={inputClass}
              value={settings.cut_enabled ? "on" : "off"}
              onChange={(e) => onChange({ cut_enabled: e.target.value === "on" })}
            >
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
          </Field>
          <Field
            label="Print mode"
            hint="Exact size draws the strip as an image so letter size stays consistent."
          >
            <select
              className={inputClass}
              value={settings.print_render_mode}
              onChange={(e) => onChange({ print_render_mode: e.target.value })}
            >
              <option value="bitmap">Exact size (recommended)</option>
              <option value="native">Printer’s built-in font</option>
            </select>
          </Field>
          {bitmap ? (
            <>
              <Field label="Text height" hint={mmHint(settings.print_glyph_px)}>
                <input
                  type="number"
                  min={8}
                  max={64}
                  className={inputClass}
                  value={settings.print_glyph_px}
                  onChange={(e) => onChange({ print_glyph_px: Number(e.target.value) })}
                />
              </Field>
              <Field
                label="Space between lines"
                hint="Extra blank space between rows of text."
              >
                <input
                  type="number"
                  min={0}
                  max={32}
                  className={inputClass}
                  value={settings.print_line_gap_px}
                  onChange={(e) =>
                    onChange({ print_line_gap_px: Number(e.target.value) })
                  }
                />
              </Field>
            </>
          ) : (
            <>
              <Field label="Built-in font">
                <select
                  className={inputClass}
                  value={settings.print_font}
                  onChange={(e) => onChange({ print_font: e.target.value })}
                >
                  <option value="a">Font A (standard)</option>
                  <option value="b">Font B (narrow)</option>
                </select>
              </Field>
              <Field
                label="Character width"
                hint="How wide each letter is (1 = normal, higher = stretched)."
              >
                <input
                  type="number"
                  min={1}
                  max={8}
                  className={inputClass}
                  value={settings.print_char_width}
                  onChange={(e) =>
                    onChange({ print_char_width: Number(e.target.value) })
                  }
                />
              </Field>
              <Field
                label="Character height"
                hint="How tall each letter is (1 = normal, higher = stretched)."
              >
                <input
                  type="number"
                  min={1}
                  max={8}
                  className={inputClass}
                  value={settings.print_char_height}
                  onChange={(e) =>
                    onChange({ print_char_height: Number(e.target.value) })
                  }
                />
              </Field>
            </>
          )}
          <Field label="Bold text">
            <select
              className={inputClass}
              value={settings.print_bold ? "on" : "off"}
              onChange={(e) => onChange({ print_bold: e.target.value === "on" })}
            >
              <option value="on">On</option>
              <option value="off">Off</option>
            </select>
          </Field>
          <Field
            label="Top margin"
            hint="Blank lines before the first text so nothing is clipped under the head."
          >
            <input
              type="number"
              min={0}
              max={20}
              className={inputClass}
              value={settings.print_lead_in}
              onChange={(e) => onChange({ print_lead_in: Number(e.target.value) })}
            />
          </Field>
          <Field
            label="Bottom feed"
            hint="Extra lines after the message so you can tear the strip cleanly."
          >
            <input
              type="number"
              min={0}
              max={40}
              className={inputClass}
              value={settings.print_tear_feed}
              onChange={(e) => onChange({ print_tear_feed: Number(e.target.value) })}
            />
          </Field>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-white hover:bg-[var(--accent-hover)]"
            onClick={onSaveAndTest}
          >
            Save and test print
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onSave}
          >
            Save format
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-white px-3 py-1.5 text-sm"
            onClick={onReset}
          >
            Reset to defaults
          </button>
        </div>
      </section>
    </div>
  );
}
