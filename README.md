# ACARS Print Bridge

Printer bridge for Hoppie / SayIntentions.AI ACARS - not an aircraft ACARS
client and not a network station.

It sits beside your aircraft's own ACARS (in the sim) and prints what that
plane receives (CPDLC, telex, weather / ATIS, and similar) on a local thermal
or Windows printer.

It does not open its own ACARS station session and does not send messages. On
Connect it watches **flight-sim** traffic to the selected ACARS network
(Hoppie or SayIntentions), forwards it to the real server, and prints from the
replies. The Hoppie website and SayIntentions companion app keep working
normally while Connected. The aircraft's logon / API key is used as-is -
nothing to enter in this app for authentication.

## Compatibility

Tested with:

- iniBuilds A340-300
- Aerosoft A340-600
- TFDi Design MD-11

**ACARS network:** Settings defaults to **Hoppie**. You can switch to
**SayIntentions.AI** (same protocol style, different host / API key). Match
that setting to what the aircraft uses.

Only ACARS traffic from the flight sim is printed. You can browse
[hoppie.nl](https://www.hoppie.nl/acars/) or keep the SayIntentions companion
app open at the same time.

It currently does **not** work with **PMDG** or **Fenix** products. Those
clients talk to a vendor cloud / datalink service instead of sending ACARS
requests from this PC to Hoppie or SayIntentions, so the bridge never sees the
traffic.

## How to use

This is the path most people want: download the release, set the printer,
Connect, fly.

### 1. Hoppie / SayIntentions logon in the aircraft

Configure your **ACARS logon** in the aircraft:

- **Hoppie:** code from [hoppie.nl/acars](https://www.hoppie.nl/acars/)
- **SayIntentions:** API key from the [Pilot Portal](https://portal.sayintentions.ai/)

Match **Settings -> ACARS network** to that choice. This app does not store or
override the aircraft key - the plane's requests pass through unchanged.

### 2. Install a printer Windows can see

Plug in and install your printer the normal Windows way (POS-80 thermal, etc.)
until it shows up under Windows printers. The app talks to printers Windows
already knows about.

### 3. Download and start the app

1. Get the latest Windows build from
   [Releases](https://github.com/tebulrich/acars-printer/releases)
   (`ACARS-Print-Bridge-*-windows-x64.exe`).
2. Run it. Accept the **Administrator / UAC** prompt. Without elevation Connect
   will fail.

Close other copies of the app first. Only one instance should run. Closing the
window fully quits the app.

### 4. Settings (do this once)

Open the **Settings** tab:

| Field | What to put |
| --- | --- |
| ACARS network | **Hoppie** (default) or **SayIntentions.AI**. Must match the aircraft. |
| Printer | Your POS / Windows printer. Use **Test print** / Format tab to confirm paper comes out. |
| Callsign filter | Optional. Empty = print every flight seen on this PC for the selected network. Set e.g. `SWR14` to only print that callsign. |
| Aircraft registration | Optional tail for the print header. With a value: `D-AILA ----  DLH4MC 04AUG 1809Z`. Leave empty to omit the tail and `----` (callsign + time only). |
| Paper width / cut | Match your roll (usually 80 mm). Leave cut/tear assist on for typical POS printers. |
| Auto-connect | On by default - Connects when the app starts (still needs Administrator). |
| Check for updates | On by default - looks for a newer GitHub release and offers one-click install of the Windows exe. |
| Sterile until | APP section. Mutes thermal prints (ACARS + SimBrief) while airborne below this AGL, or on the ground at ≥40 kt. Queued strips flush when sterile ends. Needs SimConnect (MSFS). Default 1500 ft. |
| Only when powered | APP section (off by default). When on, queue ACARS/SimBrief prints until SimConnect sees a battery master ON. If MSFS is not connected, prints are not held. |
| SimBrief | Enable + username/pilot ID to auto-print flight plan and loadsheets. See [SimBrief](#simbrief-ofp--loadsheets). |

Click **Save settings**. Put the logon / API key and flight callsign in the
**aircraft** ACARS pages. The plane's client must send the requests; this
app only watches and prints.

### 5. Connect, then use the plane

1. Click **Connect**. You should get a short "Connected" toast.
2. Leave this window running in the background.
3. In the sim, use ACARS as usual (METAR, ATIS, CPDLC, company telex, etc.).
4. Printed copies should appear on the printer; the Messages list shows what was
   stored.

Header chips show callsign, LINK, **STERILE** (or **PWR wait** when Only when
powered is holding prints), OFP status, and SIM/UTC Zulu.
**Print OFP** fetches the latest plan; **Unlock** clears the lock and allows the
same OFP to lock again on the next poll.

**Refresh** reloads the message list and bridge status. **Debug** is only for
troubleshooting (do not paste secrets into public chats - the log redacts
stored values when it can).

### 6. When you are done

Click **Disconnect**, then close the app.

### If nothing prints

- App running **as Administrator**? Connected?
- Printer selected and **Test print** works?
- Hoppie logon / SayIntentions API key correct **in the aircraft**?
- Settings -> ACARS network matches the aircraft?
- Callsign filter empty, or exactly matching the plane's callsign?
- Did the plane actually request something (weather / ATIS / etc.) after Connect?
- Is ACARS coming from the **sim** (MSFS / P3D / X-Plane)? Only sim traffic is
  printed.
- Aircraft clients that never talk to Hoppie / SayIntentions from this PC cannot
  be printed this way (see [Compatibility](#compatibility), e.g. PMDG, Fenix).
- **STERILE on?** Below your sterile AGL or taxiing ≥40 kt, prints queue and
  release when sterile ends (needs SimConnect connected).
- **PWR wait?** Only when powered is on and battery is off — prints queue until
  a battery master comes on.

## SimBrief OFP + loadsheets

Optional companion to ACARS printing (inspired by SimPrinter). When enabled:

1. Polls SimBrief about once a minute for a **new eligible OFP** (new `ofp_id`,
   scheduled out in the future or within ~60 minutes past).
2. On lock: prints **flight plan** + **preliminary** loadsheet (full route).
3. **Final** loadsheet at the earlier of T−5 before SOBT (sim Zulu if
   SimConnect is up, else wall UTC) or ~10 s continuous taxi GS 3–40 kt on the
   ground — never while sterile or (if enabled) battery off.
4. If takeoff happens without a final, prints the missed final **once after
   landing** (not in climb).
5. Unlocks after landing + grace (default 10 minutes), or earlier on a new OFP /
   Unlock / max lock (8 h). Manual Unlock also forgets the last OFP id so the
   same plan can auto-lock again.

**Print OFP** forces FP + prelim + final for the latest plan (deferred if
sterile or Only when powered). Mid-flight app restarts restore the locked OFP
from settings so final / missed-final logic can continue.

Requires a SimBrief username or numeric pilot ID. A MSFS 2024 `SimConnect.dll`
ships under `third_party/SimConnect` for sterile timing, power gating, and the
SIM clock chip (runs in-process in the main app).

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
  (LGPL; see that directory's LICENSE)
- The local MITM proxy **must bind `0.0.0.0`** so WinDivert reflection can deliver
  diverted ACARS TLS to the LAN address (loopback-only bind breaks Connect). Run
  elevated only while you need the tap; firewall rules should keep the proxy
  ports off the public internet.
- App data (SQLite, optional legacy encrypted logon, tap CA certs, debug.log) is
  under `%LOCALAPPDATA%\acars-bridge\acars-bridge`
