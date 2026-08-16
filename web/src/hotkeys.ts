import { register, unregisterAll } from "@tauri-apps/plugin-global-shortcut";
import type { Settings } from "./types";

export async function bindGlobalHotkeys(
  settings: Settings,
  onAction: (action: string) => void,
): Promise<boolean> {
  try {
    await unregisterAll();
    if (!settings.hotkeys_enabled) return true;
    for (const [action, binding] of Object.entries(settings.hotkey_bindings)) {
      const seq = (binding || "").trim();
      if (!seq) continue;
      await register(seq, (event) => {
        if (event.state !== "Pressed") return;
        onAction(action);
      });
    }
    return true;
  } catch {
    return false;
  }
}

export async function clearGlobalHotkeys(): Promise<void> {
  try {
    await unregisterAll();
  } catch {
    /* plugin missing in tests / web preview */
  }
}
