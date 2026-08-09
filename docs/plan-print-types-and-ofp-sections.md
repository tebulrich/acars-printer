# Plan: Per-type mute (#3) + OFP sections (#5) + panel actions Phase A (#7)

Status: **implemented** (randomizer removed; #3 + #5 + #7 Phase A).

## In scope

1. **#3 — Per-type mute / print** (single printer only)
2. **#5 — Thermal-friendly OFP sections**
3. **#7 — Cockpit printer panel hooks — Phase A only** (action surface + hotkeys; no hardware LEDs/status)

## Out of scope (later)

- #4 POS / thermal printer profiles
- #7 Phase B/C (Win32 printer PWR/ERR/paper status, HID/bezel LEDs)
- Auto destination ATIS/METAR/WX
- Per-type different printers
- Fenix ACARS tap

---

## Part A — Per-type mute / print (#3)

### Goal

UI toggles for which ACARS message types auto-print. Everything still uses the single `printer_destination`.

### Have now

- Types: `cpdlc`, `telex`, `inforeq`, etc.
- Hidden setting `printable_types` (CSV, default `cpdlc,telex,inforeq`) — no Settings UI / setter
- Global Auto-print on/off
- Gate in `MessageIngestionService.ingest()`
- SimBrief tickets bypass `printable_types`

### Change

- Settings → APP: checkboxes for **CPDLC**, **Telex**, **Info / ATIS-METAR** (`inforeq`)
- Persist via `printable_types` + proper setter
- Auto-print remains master switch
- Manual reprint of history rows still works
- SimBrief not in these checkboxes

### Do

1. `SettingsStore.set_printable_types` + normalize/read helpers
2. Settings UI checkboxes; save with APP settings
3. Keep existing ingest gate
4. Defaults unchanged: `cpdlc,telex,inforeq`
5. Short README note

### Accept

- Uncheck Telex → telex no longer auto-prints; others still do
- Uncheck all → nothing auto-prints (even with Auto-print on)
- Auto-print off → nothing auto-prints regardless of checkboxes
- Manual reprint still works
- Still one printer only

---

## Part B — Thermal-friendly OFP sections (#5)

### Goal

User picks which **real** SimBrief thermal tickets/sections print. No invented OFP content.

### Have now

- SimBrief JSON → tickets: flight plan, takeoff data, prelim/final loadsheet
- Fenix skips loadsheets
- Autoprint timing + **Print OFP now** + sterile/power gating

### Change

- Settings checklist, e.g. Flight plan / Takeoff data / Prelim loadsheet / Final loadsheet
- Autoprint and **Print OFP now** both honor the checklist
- Fenix loadsheet skip remains
- Optional compact layout only if cheap

### Do

1. Settings keys for enabled OFP tickets/sections
2. Settings UI checklist
3. Gate in SimBrief watcher / `simbrief/tickets.py`
4. Respect Fenix skip
5. Short README note

### Accept

- FP-only → one strip; FP+takeoff → two
- Unchecked loadsheet never prints
- Fenix still no loadsheet even if checked
- Print OFP now matches checklist

### Test (POS-80 only — no POS-58 required)

| What | How |
|------|-----|
| Section toggles | Real SimBrief OFP + **Print OFP now**; toggle sections; watch POS-80 |
| No paper waste | `console` and/or `file://` — verify which tickets fire |
| Narrow layout | Format `paper_width=58` on POS-80 (fewer columns) for compact sanity |
| Logic | Fixture SimBrief JSON → assert ticket set for checklist combos |
| Fenix | If available: loadsheets stay skipped even if checked |

---

## Part C — Panel actions Phase A (#7)

### Does API + hotkeys make sense?

**Yes.** Phase A is one shared **action layer** the UI, hotkeys, and tray call — not separate one-off handlers. No CLI/exe dual path (exe users only get the UI).

- **Hotkeys** — cockpit use (Stream Deck can send keystrokes).
- **Not in Phase A:** CLI actions, remote HTTP, printer PWR/ERR LEDs, USB bezel wiring.

Recommended Phase A surface (same actions everywhere):

| Action | Purpose |
|--------|---------|
| `reprint_last` | Reprint last successfully printed strip |
| `toggle_auto_print` | Mute/unmute auto-print |
| `test_print` | Format test page (already exists conceptually) |
| `feed` | Tear/feed assist if printer backend supports it; else no-op/document |

Optional if cheap: `print_ofp_now` (wraps existing OFP print).

### Have now

- UI: selected-row **Print** (reprint), Format test print, OFP Print/Unlock
- Tray: Show / Quit only
- CLI: `ui`, `configure`, `status`, `test-print`, `history`, `version`
- No global hotkeys; no “last printed” pointer; no shared action service

### Change

- Internal `PrinterActions` (or similar) used by UI + hotkeys + CLI
- Remember last successfully printed message/ticket for `reprint_last`
- Global hotkeys (configurable in Settings; sensible defaults; enable/disable)
- Tray menu entries for the same actions
- CLI subcommands that invoke the same actions when the app/session can reach the printer (document if UI must be running vs headless session)

### Do

1. Action service + “last printed” tracking on successful print
2. Wire UI/tray to the service
3. `QShortcut` / global hotkeys (prefer app-focused first; global only if reliable on Windows when elevated)
4. CLI: e.g. `reprint-last`, `auto-print on|off|toggle`, keep/extend `test-print`; `feed` if backend allows
5. Settings: hotkey enable + bindings
6. README: actions + hotkeys + Stream Deck tip (map keys / run CLI)

### Accept

- Hotkey / tray / CLI `reprint_last` prints the same last strip
- `toggle_auto_print` flips the existing setting and stops/starts auto-print
- `test_print` still works
- No multi-printer routing; no hardware status LEDs
- Elevated/admin Connect case: hotkeys still work while UI is focused at minimum; document global-hotkey limits if any

### Out of Phase A

- Win32 paper/offline/error polling (Phase B)
- Physical bezel / HID / LED sinks (Phase C)
- Authenticated remote HTTP API on the network

---

## Execute order (when approved)

1. Part A (#3)
2. Part B (#5) + POS-80 / console / fixture checks
3. Part C (#7 Phase A) — action service, last-print, hotkeys, tray
