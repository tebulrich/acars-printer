import { useEffect, useState, type ReactNode } from "react";
import {
  destinationFromPathDraft,
  inferPrinterInputMode,
  normalizePrinterDestination,
  parseTcpPrinter,
  tcpPrinterDestination,
  windowsSharePath,
  type PrinterInputMode,
} from "../printerDest";
import type { PrintProfile, PrinterChoice, Settings } from "../types";

interface Props {
  settings: Settings;
  printers: PrinterChoice[];
  profiles: PrintProfile[];
  onChange: (patch: Partial<Settings>) => void;
  onApplyProfile: (id: string) => void;
  onSaveProfile: () => void;
  onDeleteProfile: () => void;
  onSave: (patch?: Partial<Settings>) => void;
  onSaveAndTest: (patch?: Partial<Settings>) => void;
  onReset: () => void;
  profileId: string;
  onProfileId: (id: string) => void;
}

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

function mmHint(px: number): string {
  const mm = Math.round((px / 8) * 10) / 10;
  return `≈ ${mm} mm on POS-80`;
}

const inputClass = "inp text-sm";

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
  const tcp = parseTcpPrinter(settings.printer_destination);
  const share = windowsSharePath(settings.printer_destination);
  const mode: PrinterInputMode =
    settings.printer_input_mode === "list" ||
    settings.printer_input_mode === "ip" ||
    settings.printer_input_mode === "path"
      ? settings.printer_input_mode
      : inferPrinterInputMode(settings.printer_destination);
  const listPrinters = printers.filter((p) => !p.destination.startsWith("tcp://"));
  const listFallback = listPrinters[0]?.destination || "console";
  const listValue = listPrinters.some(
    (p) => p.destination === settings.printer_destination,
  )
    ? settings.printer_destination
    : listFallback;
  const [pathDraft, setPathDraft] = useState(share);
  const [pathFocused, setPathFocused] = useState(false);
  const [ipDraft, setIpDraft] = useState(tcp?.host ?? "");
  const [ipFocused, setIpFocused] = useState(false);

  useEffect(() => {
    if (!pathFocused) setPathDraft(share);
  }, [share, pathFocused]);
  useEffect(() => {
    if (!ipFocused) setIpDraft(tcp?.host ?? "");
  }, [tcp?.host, ipFocused]);

  function destPatch(): Partial<Settings> {
    if (mode === "path") {
      return {
        printer_input_mode: "path",
        printer_destination: destinationFromPathDraft(
          pathDraft,
          settings.printer_destination,
          listFallback,
        ),
      };
    }
    if (mode === "ip") {
      const host = ipDraft.trim();
      return {
        printer_input_mode: "ip",
        printer_destination: host
          ? tcpPrinterDestination(host, tcp?.port ?? 9100)
          : settings.printer_destination,
      };
    }
    return {
      printer_input_mode: "list",
      printer_destination: listValue,
    };
  }

  function setMode(next: PrinterInputMode) {
    if (next === "list") {
      onChange({
        printer_input_mode: "list",
        printer_destination: listValue,
      });
      return;
    }
    onChange({ printer_input_mode: next });
  }

  return (
    <div className="space-y-4">
      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Destination</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Where the strip goes, and how the paper is handled.
        </p>
        <div className="mb-3 flex flex-wrap gap-2">
          {(
            [
              ["list", "Printer list"],
              ["ip", "Network IP"],
              ["path", "Windows path"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={`rounded border px-3 py-1.5 text-sm ${
                mode === id
                  ? "border-[var(--accent)] bg-[var(--surface-alt)] font-medium text-[var(--accent)]"
                  : "border-[var(--border)] bg-[var(--btn)] text-[var(--muted)] hover:text-[var(--text)]"
              }`}
              onClick={() => setMode(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="mb-3 grid items-start gap-3 sm:grid-cols-2">
          {mode === "list" ? (
            <Field label="Printer" className="sm:col-span-2">
              <select
                className={inputClass}
                value={listValue}
                onChange={(e) =>
                  onChange({
                    printer_input_mode: "list",
                    printer_destination: normalizePrinterDestination(e.target.value),
                  })
                }
              >
                {listPrinters.map((p) => (
                  <option key={p.destination} value={p.destination}>
                    {p.label}
                  </option>
                ))}
              </select>
            </Field>
          ) : null}
          {mode === "path" ? (
            <Field
              label="Windows path"
              hint="Shared queue, for example \\192.168.1.10\POS-80"
              className="sm:col-span-2"
            >
              <input
                className={inputClass}
                value={pathDraft}
                placeholder="\\192.168.1.10\POS-80"
                spellCheck={false}
                autoComplete="off"
                onFocus={() => setPathFocused(true)}
                onChange={(e) => setPathDraft(e.target.value)}
                onBlur={() => {
                  setPathFocused(false);
                  onChange(destPatch());
                }}
              />
            </Field>
          ) : null}
          {mode === "ip" ? (
            <>
              <Field label="Network IP">
                <input
                  className={inputClass}
                  value={ipDraft}
                  placeholder="192.168.1.50"
                  spellCheck={false}
                  autoComplete="off"
                  onFocus={() => setIpFocused(true)}
                  onChange={(e) => setIpDraft(e.target.value)}
                  onBlur={() => {
                    setIpFocused(false);
                    onChange(destPatch());
                  }}
                />
              </Field>
              <Field label="Port">
                <input
                  type="number"
                  min={1}
                  max={65535}
                  className={inputClass}
                  value={tcp?.port ?? 9100}
                  onChange={(e) => {
                    const host = ipDraft.trim();
                    if (!host) return;
                    onChange({
                      printer_input_mode: "ip",
                      printer_destination: tcpPrinterDestination(
                        host,
                        Number(e.target.value),
                      ),
                    });
                  }}
                />
              </Field>
            </>
          ) : null}
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
            label="Cut paper after print"
            hint="On feeds to the cutter / tear bar."
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
        </div>
        <button
          type="button"
          className="rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
          onClick={() => onSaveAndTest(destPatch())}
        >
          Save and test print
        </button>
      </section>

      <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
        <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Strip look</h2>
        <p className="mb-3 text-sm text-[var(--muted)]">
          Apply a preset, then tweak size and margins. Destination stays as set above.
        </p>
        <div className="mb-4 flex flex-wrap items-end gap-2">
          <Field label="Preset">
            <select
              className={`${inputClass} min-w-48`}
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
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={() => onApplyProfile(profileId)}
          >
            Apply
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={() => {
              onChange(destPatch());
              onSaveProfile();
            }}
          >
            Save as…
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={onDeleteProfile}
          >
            Delete
          </button>
        </div>
        <div className="grid items-start gap-3 sm:grid-cols-2">
          <Field
            label="Print mode"
            hint="Exact size draws the strip as an image."
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
              <Field label="Space between lines">
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
                label="Character size"
                hint="Width × height. 1 is normal."
              >
                <div className="flex gap-2">
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
                </div>
              </Field>
            </>
          )}
          <Field
            label="Columns (wrap)"
            hint="Auto follows paper and font."
            className="sm:col-span-2"
          >
            <select
              className={inputClass}
              value={settings.print_columns == null ? "auto" : String(settings.print_columns)}
              onChange={(e) =>
                onChange({
                  print_columns:
                    e.target.value === "auto" ? null : Number(e.target.value),
                })
              }
            >
              <option value="auto">Auto (paper + font)</option>
              {[32, 40, 42, 48, 56, 64].map((cols) => (
                <option key={cols} value={cols}>
                  {cols} columns
                </option>
              ))}
            </select>
          </Field>
          <Field label="Top margin">
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
            hint="Top avoids clipping. Bottom leaves room to tear."
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
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={() => onSave(destPatch())}
          >
            Save format
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] bg-[var(--btn)] px-3 py-1.5 text-sm"
            onClick={onReset}
          >
            Reset look to POS-80 default
          </button>
        </div>
      </section>
    </div>
  );
}
