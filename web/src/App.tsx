import { useEffect, useRef, useState } from "react";
import { MessagesPage } from "./pages/MessagesPage";
import { SetupPage } from "./pages/SetupPage";
import {
  applyPrintProfile,
  bootApp,
  checkUpdates,
  chipTone,
  connect,
  debugClear,
  debugFolder,
  debugPaste,
  deleteUserPrintProfile,
  disconnect,
  getMessage,
  hotkey,
  installUpdate,
  listMessages,
  onBridgeEvent,
  printMessage,
  quitApp,
  refresh,
  relaunchElevated,
  isElevationError,
  mergeStatus,
  saveFormat,
  saveSettings,
  saveUserPrintProfile,
  simbriefPrint,
  simbriefUnlock,
  skipUpdate,
  testPrint,
  tick,
} from "./services/api";
import type {
  AppView,
  BridgeStatus,
  MessageRow,
  Meta,
  PrintProfile,
  PrinterChoice,
  Settings,
  Toast,
} from "./types";

const NAV: { id: AppView; label: string }[] = [
  { id: "messages", label: "Messages" },
  { id: "setup", label: "Setup" },
];

const EMPTY_STATUS: BridgeStatus = {
  running: false,
  exchanges: 0,
  last_error: null,
  network_id: null,
  network_label: "",
  link: { id: "link", text: "LINK off", state: "off" },
  chips: {
    flt: "FLT —",
    link: "LINK off",
    pwr: "PWR —",
    sterile: "STERILE off",
    ofp: "OFP —",
    clock: "UTC —",
  },
  chip_tips: {},
  auto_print: true,
  sim_connected: false,
};

function normalizeBinding(seq: string): string {
  return seq.replace(/\s+/g, "").toLowerCase();
}

function eventToBinding(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey) parts.push("Ctrl");
  if (e.shiftKey) parts.push("Shift");
  if (e.altKey) parts.push("Alt");
  if (e.metaKey) parts.push("Meta");
  const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
  if (!["Control", "Shift", "Alt", "Meta"].includes(e.key)) parts.push(key);
  return parts.join("+");
}

type UpdateCheckResult = Awaited<ReturnType<typeof checkUpdates>>;

/** Ask to install (or open the release page). Shared by startup check and Setup. */
async function promptUpdateInstall(
  result: UpdateCheckResult,
  notify: (message: string, error?: boolean) => void,
): Promise<void> {
  const release = result.release;
  if (!release) return;

  try {
    if (result.can_install) {
      const go = window.confirm(
        `Version ${release.version} is available.\n\n` +
          `Download and install now? The app will restart.`,
      );
      if (!go) return;
      notify("Downloading update...");
      const installed = await installUpdate();
      notify(`Installing ${installed.version}... restarting`);
      await quitApp();
      return;
    }

    const go = window.confirm(
      `Version ${release.version} is available.\n\nOpen the download page?`,
    );
    if (go && release.html_url) {
      const { openUrl } = await import("@tauri-apps/plugin-opener");
      await openUrl(release.html_url);
    } else if (release.version) {
      await skipUpdate(release.version);
    }
  } catch (err) {
    notify(err instanceof Error ? err.message : String(err), true);
  }
}

export default function App() {
  const [view, setView] = useState<AppView>("messages");
  const [meta, setMeta] = useState<Meta | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [status, setStatus] = useState<BridgeStatus>(EMPTY_STATUS);
  const [messages, setMessages] = useState<MessageRow[]>([]);
  const [printers, setPrinters] = useState<PrinterChoice[]>([]);
  const [profiles, setProfiles] = useState<PrintProfile[]>([]);
  const [profileId, setProfileId] = useState("pos80_default");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<MessageRow | null>(null);
  const [detailOpened, setDetailOpened] = useState(false);
  const [bootError, setBootError] = useState<string>();
  const [booting, setBooting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast | null>(null);
  const [debugOpen, setDebugOpen] = useState(false);
  const [debugText, setDebugText] = useState("");
  const [moreOpen, setMoreOpen] = useState(false);
  const toastTimer = useRef<number | null>(null);
  const settingsRef = useRef<Settings | null>(null);
  settingsRef.current = settings;

  function flash(message: string, error = false) {
    setToast({ message, error });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(
      () => setToast(null),
      error ? 8000 : 4500,
    );
  }

  async function reloadMessages() {
    const rows = await listMessages(80);
    setMessages(rows);
  }

  useEffect(() => {
    let cancelled = false;
    async function boot() {
      setBooting(true);
      try {
        const result = await bootApp();
        if (cancelled) return;
        setMeta(result.meta);
        setSettings(result.settings);
        setStatus((prev) => mergeStatus(prev, result.status));
        setMessages(result.messages);
        setPrinters(result.printers);
        setProfiles(result.profiles);
        setProfileId(result.settings.active_print_profile || "pos80_default");
        document.title = `ACARS Print Bridge ${result.meta.version}`;
        if (result.settings.auto_connect) {
          window.setTimeout(() => {
            void run(async () => {
              const st = await connect();
              setStatus((prev) => mergeStatus(prev, st));
              await reloadMessages();
              flash(`Connected — watching ${st.network_label}…`);
            });
          }, 400);
        }
        if (result.settings.check_updates) {
          window.setTimeout(() => {
            void checkUpdates(false)
              .then((r) => {
                if (!r.release) return;
                return promptUpdateInstall(r, flash);
              })
              .catch(() => undefined);
          }, 2500);
        }
      } catch (e) {
        setBootError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setBooting(false);
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const unsubs: Array<() => void> = [];
    void onBridgeEvent("status", (payload) => {
      setStatus((prev) => mergeStatus(prev, payload));
    }).then((u) => unsubs.push(u));
    void onBridgeEvent("toast", (payload) => {
      const t = payload as Toast;
      if (t && typeof t.message === "string") {
        flash(t.message, !!t.error);
      }
    }).then((u) => unsubs.push(u));
    void onBridgeEvent("new_messages", () => {
      void reloadMessages();
    }).then((u) => unsubs.push(u));
    return () => unsubs.forEach((u) => u());
  }, []);

  useEffect(() => {
    const id = window.setInterval(() => {
      void tick()
        .then((st) => setStatus((prev) => mergeStatus(prev, st)))
        .catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const s = settingsRef.current;
      if (!s?.hotkeys_enabled) return;
      const pressed = normalizeBinding(eventToBinding(e));
      for (const [action, binding] of Object.entries(s.hotkey_bindings)) {
        if (normalizeBinding(binding) === pressed) {
          e.preventDefault();
          void run(async () => {
            await hotkey(action);
            if (action === "toggle_auto_print") {
              const next = await saveSettings({});
              setSettings(next);
            }
            flash(`${action.replace(/_/g, " ")} ok`);
            await reloadMessages();
          });
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  async function run(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (isElevationError(message)) {
        flash("Requesting Administrator…", false);
        try {
          await relaunchElevated();
          return;
        } catch (elevateErr) {
          flash(
            elevateErr instanceof Error ? elevateErr.message : String(elevateErr),
            true,
          );
          return;
        }
      }
      flash(message, true);
    } finally {
      setBusy(false);
    }
  }

  const chips = status.chips ?? EMPTY_STATUS.chips;
  const chipTips = status.chip_tips ?? {};

  if (!settings) {
    return (
      <div className="flex h-full items-center justify-center text-[var(--muted)]">
        {bootError ? (
          <div className="max-w-lg rounded border border-[var(--danger)] bg-[var(--toast-error-bg)] p-4 text-[var(--danger)]">
            {bootError}
          </div>
        ) : (
          "Starting…"
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      <header className="shrink-0 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="mr-2 flex items-baseline gap-2">
            <span className="text-sm font-semibold tracking-wide">ACARS PRINT BRIDGE</span>
            <span className="text-xs text-[var(--muted)]">v{meta?.version ?? "…"}</span>
          </div>
          {(
            [
              ["flt", chips.flt],
              ["link", chips.link],
              ["pwr", chips.pwr],
              ["sterile", chips.sterile],
              ["ofp", chips.ofp],
              ["clock", chips.clock],
            ] as const
          ).map(([key, text]) => (
            <span
              key={key}
              title={chipTips[key] || ""}
              className={`rounded border border-[var(--border)] bg-[var(--bg)] px-2 py-0.5 text-xs font-medium ${chipTone(text)}`}
            >
              {text}
            </span>
          ))}
          <div className="relative ml-auto flex flex-wrap items-center gap-2">
            {!status.running ? (
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-3 py-1 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const st = await connect();
                    setStatus((prev) => mergeStatus(prev, st));
                    await reloadMessages();
                    flash("Waiting for the aircraft to send ACARS…");
                  })
                }
              >
                Connect
              </button>
            ) : (
              <button
                type="button"
                className="rounded bg-[var(--accent)] px-3 py-1 text-sm text-[#12161c] hover:bg-[var(--accent-hover)]"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const st = await disconnect();
                    setStatus((prev) => mergeStatus(prev, st));
                    await reloadMessages();
                    flash("Disconnected");
                  })
                }
              >
                Disconnect
              </button>
            )}
            <button
              type="button"
              className="rounded border border-[var(--border)] bg-[var(--btn)] px-2 py-1 text-sm"
              aria-expanded={moreOpen}
              onClick={() => setMoreOpen((open) => !open)}
            >
              More
            </button>
            {moreOpen && (
              <div className="absolute right-0 top-full z-40 mt-1 min-w-[10rem] rounded border border-[var(--border)] bg-[var(--surface)] py-1 shadow-lg">
                <button
                  type="button"
                  className="block w-full px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-alt)]"
                  onClick={() => {
                    setMoreOpen(false);
                    void run(async () => {
                      const r = await debugPaste();
                      setDebugText(r.text);
                      setDebugOpen(true);
                    });
                  }}
                >
                  Debug log
                </button>
                <button
                  type="button"
                  className="block w-full px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-alt)]"
                  onClick={() => {
                    setMoreOpen(false);
                    void run(async () => {
                      await quitApp();
                    });
                  }}
                >
                  Quit
                </button>
              </div>
            )}
          </div>
        </div>
        <nav className="mt-2 flex gap-3">
          {NAV.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`border-b-2 px-1 pb-1 text-sm ${
                view === item.id
                  ? "border-[var(--accent)] font-medium text-[var(--accent)]"
                  : "border-transparent text-[var(--muted)] hover:text-[var(--text)]"
              }`}
              onClick={() => setView(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="relative min-h-0 flex-1 overflow-hidden px-3 py-3">
        {booting && (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-start justify-center bg-[color-mix(in_srgb,var(--bg)_70%,transparent)] pt-16">
            <div className="rounded border border-[var(--border)] bg-[var(--surface)] px-4 py-2 text-sm text-[var(--muted)] shadow-sm">
              Loading…
            </div>
          </div>
        )}
        {view === "messages" && (
          <MessagesPage
            messages={messages}
            selectedId={selectedId}
            detail={detail}
            autoPrint={settings.auto_print}
            detailOpened={detailOpened}
            running={status.running}
            onSelect={(id) =>
              void run(async () => {
                setSelectedId(id);
                setDetailOpened(true);
                setDetail(await getMessage(id));
              })
            }
            onRefresh={() =>
              void run(async () => {
                const r = await refresh();
                setMessages(r.messages);
                setStatus((prev) => mergeStatus(prev, r.status));
              })
            }
            onPrint={() =>
              void run(async () => {
                if (!selectedId) return;
                const r = await printMessage(selectedId);
                flash(r.result === "deferred" ? "Print deferred" : "Printed");
                await reloadMessages();
              })
            }
            onHide={() => {
              setDetailOpened(false);
              setDetail(null);
              setSelectedId(null);
            }}
          />
        )}
        {view === "setup" && (
          <SetupPage
            settings={settings}
            printers={printers}
            profiles={profiles}
            profileId={profileId}
            tapConnected={status.running}
            onProfileId={setProfileId}
            onChange={(patch) => setSettings({ ...settings, ...patch })}
            onApplyProfile={(id) =>
              void run(async () => {
                const next = await applyPrintProfile(id);
                setSettings(next);
                flash(`Applied profile ${id}`);
              })
            }
            onSaveProfile={() =>
              void run(async () => {
                const name = window.prompt("Profile name");
                if (!name) return;
                await saveFormat(settings);
                const r = await saveUserPrintProfile(name);
                setProfiles(r.profiles);
                setSettings(r.settings);
                setProfileId(name);
                flash(`Saved profile ${name}`);
              })
            }
            onDeleteProfile={() =>
              void run(async () => {
                const r = await deleteUserPrintProfile(profileId);
                setProfiles(r.profiles);
                flash(`Deleted ${profileId}`);
              })
            }
            onSaveFormat={() =>
              void run(async () => {
                const next = await saveFormat(settings);
                setSettings((prev) => (prev ? { ...prev, ...next } : next));
                flash("Format saved");
              })
            }
            onSaveAndTest={() =>
              void run(async () => {
                const next = await saveFormat(settings);
                setSettings((prev) => (prev ? { ...prev, ...next } : next));
                await testPrint();
                flash("Test print sent");
              })
            }
            onReset={() =>
              void run(async () => {
                const next = await applyPrintProfile("pos80_default");
                setSettings(next);
                setProfileId("pos80_default");
                flash("Reset to POS-80 default");
              })
            }
            onSaveSettings={() =>
              void run(async () => {
                const next = await saveSettings(settings);
                setSettings(next);
                if (next.station_blocked) {
                  flash(next.station_blocked, true);
                } else {
                  flash("Settings saved");
                }
                await reloadMessages();
              })
            }
            onPrintOfp={() =>
              void run(async () => {
                const r = await simbriefPrint();
                setStatus((prev) => mergeStatus(prev, r.status));
                flash(r.message);
              })
            }
            onUnlockOfp={() =>
              void run(async () => {
                const r = await simbriefUnlock();
                setStatus((prev) => mergeStatus(prev, r.status));
                flash(r.message);
              })
            }
            onCheckUpdates={() =>
              void run(async () => {
                const r = await checkUpdates(true);
                if (!r.release) {
                  flash("You're up to date");
                  return;
                }
                await promptUpdateInstall(r, flash);
              })
            }
            onOpenCompanion={() =>
              void run(async () => {
                if (!settings.companion_url) {
                  flash("Enable companion and Save settings first", true);
                  return;
                }
                const { openUrl } = await import("@tauri-apps/plugin-opener");
                await openUrl(settings.companion_url);
              })
            }
          />
        )}
      </main>

      {toast && (
        <div
          className={`fixed bottom-3 left-1/2 z-50 max-w-xl -translate-x-1/2 rounded border px-3 py-2 text-sm shadow ${
            toast.error
              ? "border-[var(--danger)] bg-[var(--toast-error-bg)] text-[var(--danger)]"
              : "border-[var(--border)] bg-[var(--surface)] text-[var(--text)]"
          }`}
        >
          {toast.message}
        </div>
      )}

      {debugOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
          <div className="flex max-h-[80vh] w-full max-w-3xl flex-col rounded border border-[var(--border)] bg-[var(--surface)] shadow-lg">
            <div className="flex items-center justify-between border-b border-[var(--border)] px-3 py-2">
              <h3 className="text-sm font-semibold">Debug log</h3>
              <div className="flex gap-2">
                <button
                  type="button"
                  className="rounded border border-[var(--border)] px-2 py-1 text-sm"
                  onClick={() => void navigator.clipboard.writeText(debugText)}
                >
                  Copy
                </button>
                <button
                  type="button"
                  className="rounded border border-[var(--border)] px-2 py-1 text-sm"
                  onClick={() =>
                    void run(async () => {
                      const folder = await debugFolder();
                      const { openPath } = await import("@tauri-apps/plugin-opener");
                      await openPath(folder.path);
                    })
                  }
                >
                  Open folder
                </button>
                <button
                  type="button"
                  className="rounded border border-[var(--border)] px-2 py-1 text-sm"
                  onClick={() =>
                    void run(async () => {
                      await debugClear();
                      const r = await debugPaste();
                      setDebugText(r.text);
                    })
                  }
                >
                  Clear
                </button>
                <button
                  type="button"
                  className="rounded border border-[var(--border)] px-2 py-1 text-sm"
                  onClick={() => setDebugOpen(false)}
                >
                  Close
                </button>
              </div>
            </div>
            <pre className="min-h-0 flex-1 overflow-auto bg-[var(--mono-bg)] p-3 font-mono text-xs text-[var(--mono-fg)]">
              {debugText}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
