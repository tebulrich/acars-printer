# ACARS Print Bridge

Printer bridge for Hoppie / SayIntentions.AI ACARS — not an aircraft ACARS
client and not a network station.

It sits beside your aircraft’s own ACARS (in the sim) and prints what that
plane receives (CPDLC, telex, weather / ATIS, and similar) on a local thermal
or Windows printer.

It does not open its own ACARS station session and does not send messages. On
Connect it intercepts **flight-sim** traffic to the selected network host
(`www.hoppie.nl` or `acars.sayintentions.ai`), forwards each request to the real
server, and prints from the replies. Browsers and companion apps keep a direct
path (no hosts-file redirect). Disconnect restores normal routing. The
aircraft’s logon / API key is used as-is — nothing to enter in this app for
authentication.

## Compatibility

Tested with:

- iniBuilds A340-300
- Aerosoft A340-600
- TFDi Design MD-11

**ACARS network:** Settings defaults to **Hoppie** (`www.hoppie.nl`). You can
switch to **SayIntentions.AI** (`acars.sayintentions.ai`) — same Hoppie-style
protocol, different host / API key. The aircraft must use that same network;
this app only intercepts the selected host on this PC.

It currently does **not** work with **PMDG** or **Fenix** products. Those
clients talk to a vendor cloud / datalink service instead of sending Hoppie
(or SayIntentions) requests directly from this PC to the ACARS host, so the
tap never sees the traffic and cannot print it.

**Website / companion coexistence:** neither network rewrites the hosts file.
WinDivert only intercepts flight-sim processes (MSFS / P3D / X-Plane / FSX).
You can browse [hoppie.nl](https://www.hoppie.nl/acars/) or run the
SayIntentions companion app while Connected; only aircraft ACARS inside the
sim is MITM’d and printed.

| Mode | Hosts file | What is tapped |
| --- | --- | --- |
| Hoppie (default) | Left alone | Flight-sim → Hoppie only |
| SayIntentions.AI | Left alone | Flight-sim → SI only (SI companion denylisted) |

## How to use

This is the path most people want: download the release, set the printer,
Connect, fly.

### 1. Hoppie / SayIntentions logon in the aircraft

Configure your **ACARS logon** in the aircraft:

- **Hoppie:** code from [hoppie.nl/acars](https://www.hoppie.nl/acars/)
- **SayIntentions:** API key from the [Pilot Portal](https://portal.sayintentions.ai/)

Match **Settings → ACARS network** to that choice. This app does not store or
override the aircraft key — the plane’s requests pass through unchanged.

### 2. Install a printer Windows can see

Plug in and install your printer the normal Windows way (POS-80 thermal, etc.)
until it shows up under Windows printers. The app talks to printers Windows
already knows about.

### 3. Download and start the app

1. Get the latest Windows build from
   [Releases](https://github.com/tebulrich/acars-printer/releases)
   (`ACARS-Print-Bridge-…-windows-x64.exe`).
2. Run it. Accept the **Administrator / UAC** prompt. Without elevation the tap
   cannot bind ports 80/443 or open WinDivert, so Connect will fail.

Close other copies of the app first. Only one instance should run. Closing the
window fully quits the app.

### 4. Settings (do this once)

Open the **Settings** tab:

| Field | What to put |
| --- | --- |
| ACARS network | **Hoppie** (default) or **SayIntentions.AI**. Must match the aircraft. |
| Printer | Your POS / Windows printer. Use **Test print** / Format tab to confirm paper comes out. |
| Callsign filter | Optional. Empty = print every flight seen on this PC for the selected network. Set e.g. `SWR14` to only print that callsign. |
| Aircraft registration | Optional tail for the print header (Format tab). With a value: `D-AILA ----  DLH4MC 04AUG 1809Z`. Leave empty to omit the tail and `----` (callsign + time only). |
| Paper width / cut | Match your roll (usually 80 mm). Leave cut/tear assist on for typical POS printers. |
| Auto-connect | On by default — Connects the tap when the app starts (still needs Administrator). |
| Check for updates | On by default — looks for a newer GitHub release and offers one-click install of the Windows exe. |

Click **Save settings**. Put the logon / API key and flight callsign in the
**aircraft** ACARS pages. The plane’s client must send the requests; this
app only watches and prints.

### 5. Connect, then use the plane

1. Click **Connect**. You should get a short “Connected” toast.
2. Leave this window running in the background (Hoppie website and the
   SayIntentions companion app can stay open too).
3. In the sim, use ACARS as usual (METAR, ATIS, CPDLC, company telex, …).
4. Printed copies should appear on the printer; the Messages list shows what was
   stored.

**Refresh** reloads the message list and bridge status. **Debug** is only for
troubleshooting (do not paste secrets into public chats — the log redacts
stored values when it can).

While Connected, browsing the ACARS website in a normal browser is fine — only
flight-sim processes are diverted.

### 6. When you are done

Click **Disconnect**. That stops intercepting ACARS traffic and restores normal
access. You can then close the app.

### If nothing prints

- App running **as Administrator**? Connected?
- Printer selected and **Test print** works?
- Hoppie logon / SayIntentions API key correct **in the aircraft**?
- Settings → ACARS network matches the aircraft?
- Callsign filter empty, or exactly matching the plane’s callsign?
- Did the plane actually request something (weather / ATIS / etc.) after Connect?
- For either network: is ACARS coming from the **sim** (MSFS / P3D / X-Plane)?
  Only sim processes are tapped; browsers and the SI companion app are left alone.
- Aircraft clients that never talk to the selected host’s `connect.html` on this
  PC cannot be printed this way (see [Compatibility](#compatibility) — e.g.
  PMDG, Fenix).

## Requirements

- Windows
- Administrator rights when Connected
- A working Hoppie or SayIntentions ACARS setup in the aircraft
- A printer destination configured in the app
- Python 3.12+ and [uv](https://github.com/astral-sh/uv) only if you build or
  run from source

## Build the Windows exe yourself

```bat
uv sync --group dev
scripts\build_windows_exe.bat
```

(PowerShell alternative: `.\scripts\build_windows_exe.ps1`)

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
- SayIntentions drop-in endpoint:
  [Integrate with SayIntentions.AI ACARS/CPDLC](https://kb.sayintentions.ai/article/integrate-with-sayintentions-ai-acars-cpdlc)
- WinDivert 2.2.2 binaries used by the tap live under `third_party/WinDivert`
  (LGPL; see that directory’s LICENSE)
- App data (SQLite, optional legacy encrypted logon, tap CA certs, debug.log) is
  under `%LOCALAPPDATA%\acars-bridge\acars-bridge`
