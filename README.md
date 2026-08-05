# ACARS Print Bridge

Printer bridge for Hoppie ACARS — not an aircraft ACARS client and not a
Hoppie station.

It sits beside your aircraft’s own Hoppie ACARS (in the sim) and prints what
that plane receives (CPDLC, telex, weather / ATIS, and similar) on a local
thermal or Windows printer.

It does not open its own Hoppie station session and does not send ACARS
messages. On Connect it intercepts traffic to `www.hoppie.nl`, forwards each
request to the real server, and prints from the replies. Disconnect restores
normal DNS / routing. The aircraft’s Hoppie logon is used as-is.

## Compatibility

Tested with:

- iniBuilds A340-300
- Aerosoft A340-600
- TFDi Design MD-11

It currently does **not** work with **PMDG** or **Fenix** products. Those
clients talk to a vendor cloud / datalink service instead of sending Hoppie
requests directly from this PC to `www.hoppie.nl`, so the tap never sees the
traffic and cannot print it.

## How to use

This is the path most people want: download the release, set the printer,
Connect, fly.

### 1. Hoppie logon in the aircraft

Configure your **ACARS logon code** in the aircraft (from
[hoppie.nl/acars](https://www.hoppie.nl/acars/)). This app does not store or
override that code — the plane’s requests pass through unchanged.

### 2. Install a printer Windows can see

Plug in and install your printer the normal Windows way (POS-80 thermal, etc.)
until it shows up under Windows printers. The app talks to printers Windows
already knows about.

### 3. Download and start the app

1. Get the latest Windows build from
   [Releases](https://github.com/tebulrich/acars-printer/releases)
   (`ACARS-Print-Bridge-…-windows-x64.exe`).
2. Run it. Accept the **Administrator / UAC** prompt. Without elevation the tap
   cannot bind ports 80/443 or edit the hosts file, so Connect will fail.

Close other copies of the app first. Only one instance should run. Closing the
window fully quits the app.

### 4. Settings (do this once)

Open the **Settings** tab:

| Field | What to put |
| --- | --- |
| Printer | Your POS / Windows printer. Use **Test print** / Format tab to confirm paper comes out. |
| Callsign filter | Optional. Empty = print every Hoppie flight seen on this PC. Set e.g. `SWR14` to only print that callsign. |
| Aircraft registration | Optional tail for the print header (Format tab). With a value: `D-AILA ----  DLH4MC 04AUG 1809Z`. Leave empty to omit the tail and `----` (callsign + time only). |
| Paper width / cut | Match your roll (usually 80 mm). Leave cut/tear assist on for typical POS printers. |
| Auto-connect | On by default — Connects the tap when the app starts (still needs Administrator). |
| Check for updates | On by default — looks for a newer GitHub release and offers one-click install of the Windows exe. |

Click **Save settings**. Put the Hoppie logon and flight callsign in the
**aircraft** ACARS pages. The plane’s client must send the Hoppie requests; this
app only watches and prints.

### 5. Connect, then use the plane

1. Click **Connect**. You should get a short “Connected” toast.
2. Leave this window running in the background.
3. In the sim, use ACARS as usual (METAR, ATIS, CPDLC, company telex, …).
4. Printed copies should appear on the printer; the Messages list shows what was
   stored.

**Refresh** reloads the message list and bridge status. **Debug** is only for
troubleshooting (do not paste secrets into public chats — the log redacts
stored values when it can).

While Connected, avoid browsing `www.hoppie.nl` in a browser on the same PC —
that traffic goes through the tap too and just adds noise.

### 6. When you are done

Click **Disconnect**. That stops intercepting Hoppie and restores normal access.
You can then close the app.

### If nothing prints

- App running **as Administrator**? Connected?
- Printer selected and **Test print** works?
- Hoppie logon correct **in the aircraft**?
- Callsign filter empty, or exactly matching the plane’s callsign?
- Did the plane actually request something (weather / ATIS / etc.) after Connect?
- Aircraft clients that never talk to Hoppie’s `connect.html` on this PC cannot
  be printed this way (see [Compatibility](#compatibility) — e.g. PMDG, Fenix).

## Requirements

- Windows
- Administrator rights when Connected
- A working Hoppie ACARS setup in the aircraft
- A printer destination configured in the app
- Python 3.12+ and [uv](https://github.com/astral-sh/uv) only if you build or
  run from source

## Build the Windows exe yourself

```powershell
uv sync --group dev
.\scripts\build_windows_exe.ps1
```

Output: `dist\ACARS Print Bridge.exe` (run elevated).

## Run from source

```powershell
uv sync
# elevated shell
uv run acars-bridge ui
```

## CLI

```powershell
uv run acars-bridge version
uv run acars-bridge configure --callsign SWR14 --printer win32://POS-80
uv run acars-bridge status
uv run acars-bridge test-print
uv run acars-bridge history
```

The desktop UI Connect path is the local tap described above.

## Tests

```powershell
uv run pytest
```

## Notes

- Protocol reference: [Hoppie ACARS server API](https://www.hoppie.nl/acars/system/tech.html)
- WinDivert 2.2.2 binaries used by the tap live under `third_party/WinDivert`
  (LGPL; see that directory’s LICENSE)
- App data (SQLite, optional legacy encrypted logon, tap CA certs, debug.log) is
  under `%LOCALAPPDATA%\acars-bridge\acars-bridge`
