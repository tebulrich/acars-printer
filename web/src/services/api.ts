import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  BootResult,
  BridgeStatus,
  MessageRow,
  PrintProfile,
  PrinterChoice,
  Settings,
} from "../types";

async function bridge<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  return invoke<T>("bridge_command", { command, args });
}

export function bootApp() {
  return bridge<BootResult>("boot");
}

export function getSettings() {
  return bridge<Settings>("get_settings");
}

export function saveSettings(settings: Partial<Settings>) {
  return bridge<Settings>("save_settings", settings as Record<string, unknown>);
}

export function saveFormat(settings: Partial<Settings>) {
  return bridge<Settings>("save_format", settings as Record<string, unknown>);
}

export function listPrinters() {
  return bridge<PrinterChoice[]>("list_printers");
}

export function listPrintProfiles() {
  return bridge<PrintProfile[]>("list_print_profiles");
}

export function applyPrintProfile(profile_id: string) {
  return bridge<Settings>("apply_print_profile", { profile_id });
}

export function saveUserPrintProfile(name: string) {
  return bridge<{ profiles: PrintProfile[]; settings: Settings }>("save_user_print_profile", {
    name,
  });
}

export function deleteUserPrintProfile(profile_id: string) {
  return bridge<{ profiles: PrintProfile[] }>("delete_user_print_profile", { profile_id });
}

export function listMessages(limit = 80) {
  return bridge<MessageRow[]>("list_messages", { limit });
}

export function getMessage(message_id: number) {
  return bridge<MessageRow>("get_message", { message_id });
}

export function printMessage(message_id: number) {
  return bridge<{ result: string }>("print_message", { message_id });
}

export function reprintLast() {
  return bridge<{ result: string }>("reprint_last");
}

export function testPrint() {
  return bridge<{ ok: boolean }>("test_print");
}

export function feed(lines?: number) {
  return bridge<{ ok: boolean }>("feed", lines === undefined ? {} : { lines });
}

export function toggleAutoPrint() {
  return bridge<{ auto_print: boolean }>("toggle_auto_print");
}

export function connect() {
  return bridge<BridgeStatus>("connect");
}

export function disconnect() {
  return bridge<BridgeStatus>("disconnect");
}

export function refresh() {
  return bridge<{ checked: boolean; messages: MessageRow[]; status: BridgeStatus }>("refresh");
}

export function getStatus() {
  return bridge<BridgeStatus>("get_status");
}

export function tick() {
  return bridge<BridgeStatus>("tick");
}

export function simbriefPrint() {
  return bridge<{ message: string; status: BridgeStatus }>("simbrief_print");
}

export function simbriefUnlock() {
  return bridge<{ message: string; status: BridgeStatus }>("simbrief_unlock");
}

export function debugPaste() {
  return bridge<{ text: string }>("debug_paste");
}

export function debugClear() {
  return bridge<{ cleared: boolean }>("debug_clear");
}

export function debugFolder() {
  return bridge<{ path: string; log?: string }>("debug_folder");
}

export function checkUpdates(manual = true) {
  return bridge<{
    release: {
      version: string;
      notes: string;
      asset_url: string;
      html_url: string;
      asset_name?: string;
    } | null;
    can_install?: boolean;
  }>("check_updates", { manual });
}

export function installUpdate() {
  return bridge<{ restarting: boolean; version: string }>("install_update");
}

export function skipUpdate(version: string) {
  return bridge<{ skipped: string }>("skip_update", { version });
}

export function hotkey(action: string) {
  return bridge<unknown>("hotkey", { action });
}

export function quitApp() {
  return invoke<void>("quit_app");
}

export function companionStatus() {
  return bridge<{
    enabled: boolean;
    station_enabled: boolean;
    port: number;
    url?: string;
    server_running?: boolean;
    station_polling?: boolean;
    station_error?: string | null;
  }>("companion_status");
}

export function drainEvents() {
  return bridge<
    Array<{ ok: boolean; event?: string; data?: unknown }>
  >("drain_events");
}

export async function relaunchElevated(): Promise<void> {
  await invoke("relaunch_elevated");
}

export function isElevationError(message: string): boolean {
  // Only the bridge connect gate — do NOT match printer/driver text that may
  // casually mention Administrator / elevation (that was blanking the UI).
  return message.includes("NEEDS_ELEVATION:");
}

export async function onBridgeEvent(
  event: string,
  handler: (payload: unknown) => void,
): Promise<UnlistenFn> {
  return listen(`bridge://${event}`, (e) => handler(e.payload));
}

/** Map chip text to a subtle style class. */
export function chipTone(text: string | null | undefined): string {
  const t = (text ?? "").toLowerCase();
  if (!t) return "text-[var(--muted)]";
  if (
    t.includes("issue") ||
    t.includes("fail") ||
    t.includes("reject") ||
    t.includes("in use")
  ) {
    return "text-[var(--danger)]";
  }
  if (t.includes("ok") || t.includes("on") || t.includes("seen")) return "text-[var(--success)]";
  if (t.includes("…") || t.includes("waiting") || t.includes("q")) return "text-[var(--accent)]";
  return "text-[var(--muted)]";
}

/** Keep UI from crashing if a partial status payload arrives. */
export function mergeStatus(
  prev: BridgeStatus,
  payload: unknown,
): BridgeStatus {
  if (!payload || typeof payload !== "object") return prev;
  const p = payload as Partial<BridgeStatus>;
  return {
    ...prev,
    ...p,
    link: { ...prev.link, ...(p.link ?? {}) },
    chips: { ...prev.chips, ...(p.chips ?? {}) },
    chip_tips: { ...prev.chip_tips, ...(p.chip_tips ?? {}) },
  };
}
