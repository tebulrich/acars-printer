import type { Settings } from "../types";

interface Props {
  settings: Settings;
  onChange: (patch: Partial<Settings>) => void;
  onSave: () => void;
}

const inputClass = "inp text-sm";

const HOTKEY_LABELS: Record<string, string> = {
  reprint_last: "Reprint last message",
  toggle_auto_print: "Toggle auto-print",
  test_print: "Test print",
  feed: "Feed paper",
};

function eventToBinding(e: React.KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push("Ctrl");
  if (e.shiftKey) parts.push("Shift");
  if (e.altKey) parts.push("Alt");
  if (e.metaKey) parts.push("Meta");
  const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  if (!["Control", "Shift", "Alt", "Meta"].includes(e.key)) parts.push(key);
  return parts.join("+");
}

export function HotkeysPage({ settings, onChange, onSave }: Props) {
  return (
    <section className="rounded border border-[var(--border)] bg-[var(--surface)] p-4">
      <h2 className="mb-1 text-sm font-semibold text-[var(--text)]">Keyboard shortcuts</h2>
      <p className="mb-3 text-sm text-[var(--muted)]">
        Click a field and press the keys (for example Ctrl+Shift+R). These also
        work while the sim has focus. Backspace clears a shortcut.
      </p>
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={settings.hotkeys_enabled}
          onChange={(e) => onChange({ hotkeys_enabled: e.target.checked })}
        />
        Enable keyboard shortcuts
      </label>
      <div className="grid max-w-lg gap-3">
        {settings.hotkey_actions.map((action) => (
          <label key={action} className="grid gap-1 text-sm">
            <span className="font-medium text-[var(--text)]">
              {HOTKEY_LABELS[action] || action.replace(/_/g, " ")}
            </span>
            <input
              className={inputClass}
              readOnly
              value={settings.hotkey_bindings[action] || ""}
              placeholder="Click, then press keys"
              onKeyDown={(e) => {
                e.preventDefault();
                if (e.key === "Backspace" || e.key === "Delete") {
                  onChange({
                    hotkey_bindings: {
                      ...settings.hotkey_bindings,
                      [action]: "",
                    },
                  });
                  return;
                }
                const binding = eventToBinding(e);
                if (!binding || ["Ctrl", "Shift", "Alt", "Meta"].includes(binding)) {
                  return;
                }
                onChange({
                  hotkey_bindings: {
                    ...settings.hotkey_bindings,
                    [action]: binding,
                  },
                });
              }}
            />
          </label>
        ))}
      </div>
      <button
        type="button"
        className="mt-4 rounded bg-[var(--accent)] px-3 py-1.5 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
        onClick={onSave}
      >
        Save settings
      </button>
    </section>
  );
}
