# ACARS Print Bridge

Standalone **Hoppie ACARS** client with thermal printing and a desktop UI.

- **Station mode (default):** `poll` + send telex/CPDLC replies + print. You own the callsign.
- **Observer mode:** `peek` + print only. Use when PMDG / TFDi / another client already holds the callsign **with the same Hoppie logon**.
- **Requests (Station):** METAR / TAF / ATIS (ARR|DEP), PDC, and manual position reports — Fenix-like fields on the Requests tab.

No aircraft SDKs. Windows-first; Linux/macOS work for development and most features.

## Desktop UI (recommended)

Built with **PySide6 (Qt)** — native widgets, OS fonts, and DPI scaling. No canvas-drawn controls.

- Live status chips: mode, callsign, link, UTC
- Message traffic list + detail pane
- One-tap CPDLC replies: WILCO / ROGER / UNABLE / STANDBY
- Telex compose bar
- Settings: mode switch, logon (masked), printer dropdown (console + installed printers), paper width, auto-print
- Background monitor with Start / Pause / Check now
- Desktop notifications on new traffic

```bash
uv sync
uv run acars-bridge ui
```

Shortcuts are **unset by default**. Configure them under **Shortcuts** (global — work even when the window is unfocused). Use Ctrl/Alt/Meta chords or F-keys.

Reply letter keys are disabled while typing in a text field.

Configure inside **Settings**, or via CLI first:

```bash
uv run acars-bridge configure \
  --callsign SWR14 \
  --logon YOUR_HOPPIE_LOGON \
  --mode station \
  --printer console \
  --width 80
```

## CLI (still available)

```bash
uv run acars-bridge poll --once
uv run acars-bridge observe --once
uv run acars-bridge send-telex SWROPS "HELLO OPS"
uv run acars-bridge request-metar EGLL
uv run acars-bridge request-atis EGLL --side dep
uv run acars-bridge request-pdc --station EDDF --dep EDDF --dest EDDM --stand A36 --atis D
uv run acars-bridge send-position EDUU --lat N5030.0 --lon E00845.0 --alt FL360 --time 1435Z
uv run acars-bridge reply 1 WILCO
uv run acars-bridge history
uv run acars-bridge test-print
```

Requests require **Station** mode (same logon as the flight).

## Observer note

Observer creates a **second** HTTP client to Hoppie (`peek`). It does not share the aircraft connection. Keep frequency low (≥45–60s).

You must use the **same Hoppie logon** as the aircraft client. Hoppie rejects peek when the callsign is locked by a different account — so you cannot observe someone else’s flight with your own logon.

## Printing

```bash
uv run acars-bridge test-print --destination file:///tmp/acars-test.bin
uv run acars-bridge configure --printer tcp://192.168.1.50:9100
# Installed system printer (CUPS on Linux/macOS, Win32 on Windows):
uv run acars-bridge configure --printer "cups://Your_Printer_Name"
uv run acars-bridge configure --printer "win32://Your Printer Name"
```

- `cups://Name` — **driver** text (Brother/HP laser/inkjet).
- `cups-raw://Name` — **POS / ESC/POS** raw bytes on that CUPS queue (thermal).
- `tcp://host:9100` — network ESC/POS thermal directly (best for POS-80).

In the UI each CUPS queue appears twice (`· driver` / `· POS ESC/POS`) so you can keep both printers configured.

**Windows USB POS-80:** Windows SMB printer sharing often returns `ACCESS_DENIED` for raw jobs from Linux. Run [`scripts/windows_pos_raw_bridge.ps1`](scripts/windows_pos_raw_bridge.ps1) on the Windows PC, then point the app at `tcp://192.168.1.55:9100`.

## Tests

```bash
uv run pytest
```

Automated tests never call live Hoppie or a physical printer.

## Docs

- [`PLAN.md`](PLAN.md)
- [`docs/HOPPIE_NOTES.md`](docs/HOPPIE_NOTES.md)
