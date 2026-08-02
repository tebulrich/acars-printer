# ACARS Print Bridge

Windows app that sits beside a Hoppie ACARS aircraft client and prints what the
plane receives (CPDLC, telex, weather / ATIS, and similar) on a local thermal or
Windows printer.

It does not open its own Hoppie station session. On Connect it intercepts
traffic to `www.hoppie.nl`, forwards each request to the real server, and
prints from the replies. Disconnect restores normal DNS / routing.

Requires a [Hoppie](https://www.hoppie.nl/acars/) logon code in Settings (the
same code the aircraft uses). Optional callsign filter limits printing to one
flight.

## Requirements

- Windows
- Python 3.12+ and [uv](https://github.com/astral-sh/uv) (for building or
  running from source)
- Administrator rights when Connected (ports 80/443, hosts file, WinDivert)
- A printer destination configured in Settings (ESC/POS thermal or another
  Windows printer)

## Run the Windows build

```powershell
uv sync --group dev
.\scripts\build_windows_exe.ps1
```

Start `dist\ACARS Print Bridge.exe` and accept the UAC prompt.

1. Settings → Hoppie logon, printer, optional callsign filter → Save
2. Connect
3. Use ACARS in the aircraft as usual

Refresh on the Messages tab reloads the list and bridge status. Debug opens the
local support log (`%LOCALAPPDATA%\acars-bridge\acars-bridge\debug.log`).

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
- App data (SQLite, encrypted logon, tap CA certs) is under
  `%LOCALAPPDATA%\acars-bridge\acars-bridge`
