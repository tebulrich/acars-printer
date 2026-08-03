# ACARS Print Bridge

Windows app that sits beside a Hoppie ACARS aircraft client and prints what the
plane receives (CPDLC, telex, weather / ATIS, and similar) on a local thermal or
Windows printer.

It does not open its own Hoppie station session. On Connect it intercepts
traffic to `www.hoppie.nl`, forwards each request to the real server, and
prints from the replies. Disconnect restores normal DNS / routing.

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

This is the path most people want: download the release, set two things, Connect,
fly.

### 1. Get a Hoppie logon code

1. Open [hoppie.nl/acars](https://www.hoppie.nl/acars/).
2. Request / look up your **ACARS logon code** (the secret string clients put in
   the aircraft ACARS setup — not your Windows username and not a callsign).
3. Keep that code handy. You will enter the **same** code in the aircraft and
   in this app.

If ACARS already works in your plane, you already have the code — use that one.

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
window (or minimizing) sends the app to the system tray — right-click the tray
icon → **Quit** to exit fully.

### 4. Settings (do this once)

Open the **Settings** tab:

| Field | What to put |
| --- | --- |
| Hoppie logon | Your Hoppie ACARS logon code from step 1. Leave blank later if it already says it is stored. |
| Printer | Your POS / Windows printer. Use **Test print** on the Messages side to confirm paper comes out. |
| Callsign filter | Optional. Empty = print every Hoppie flight seen on this PC. Set e.g. `SWR14` to only print that callsign. |
| Aircraft registration | Optional tail for the print header (`REG D-AIXX`). Leave empty to omit REG. |
| Paper width / cut | Match your roll (usually 80 mm). Leave cut/tear assist on for typical POS printers. |
| Auto-connect | On by default — Connects the tap when the app starts (still needs Administrator). |
| Check for updates | On by default — looks for a newer GitHub release and offers one-click install of the Windows exe. |

Click **Save settings**.

Also put the **same logon** and your **flight callsign** in the aircraft ACARS
pages. The plane must actually send Hoppie requests; this app only watches and
prints.

### 5. Connect, then use the plane

1. Click **Connect**. You should get a short “Connected” toast.
2. Leave this window running in the background.
3. In the sim, use ACARS as usual (METAR, ATIS, CPDLC, company telex, …).
4. Printed copies should appear on the printer; the Messages list shows what was
   stored.

**Refresh** reloads the message list and bridge status. **Debug** is only for
troubleshooting (do not paste your logon into public chats — the log redacts it
when it can).

While Connected, avoid browsing `www.hoppie.nl` in a browser on the same PC —
that traffic goes through the tap too and just adds noise.

### 6. When you are done

Click **Disconnect**. That stops intercepting Hoppie and restores normal access.
You can then close the app.

### If nothing prints

- App running **as Administrator**? Connected?
- Printer selected and **Test print** works?
- Same Hoppie logon in Settings and in the aircraft?
- Callsign filter empty, or exactly matching the plane’s callsign?
- Did the plane actually request something (weather / ATIS / etc.) after Connect?
- Aircraft clients that never talk to Hoppie’s `connect.html` on this PC cannot
  be printed this way (see [Compatibility](#compatibility) — e.g. PMDG, Fenix).

## Requirements

- Windows
- Administrator rights when Connected
- A Hoppie ACARS logon code
- A printer destination configured in Settings
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
uv run acars-bridge configure --callsign SWR14 --logon <code>
uv run acars-bridge status
uv run acars-bridge test-print
uv run acars-bridge history
```

`observe` still exists for peek-based use; the UI Connect path is the tap
described above.

## Tests

```powershell
uv run pytest
```

## Notes

- Protocol reference: [Hoppie ACARS server API](https://www.hoppie.nl/acars/system/tech.html)
- WinDivert 2.2.2 binaries used by the tap live under `third_party/WinDivert`
  (LGPL; see that directory’s LICENSE)
- App data (SQLite, encrypted logon, tap CA certs, debug.log) is under
  `%LOCALAPPDATA%\acars-bridge\acars-bridge`
