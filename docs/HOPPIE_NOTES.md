# Hoppie integration notes

Official API: <https://www.hoppie.nl/acars/system/tech.html>

## Connections

Hoppie uses short HTTP request/response cycles — not a shared persistent socket.

- **Station:** this app `poll`s (consumes queue, takes callsign lock).
- **Observer:** this app `peek`s while another client (e.g. PMDG/TFDi) `poll`s
  with the **same Hoppie logon**. That is two clients / two request streams.
  Peek does not consume like poll and does not show you online, but it is
  heavier (up to ~24h of messages). Keep Observer intervals conservative
  (default ≥ 45–60s, with jitter).

## Callsign lock

Except for `peek` and `ping`, Hoppie locks `logon + network + callsign` (~100s TTL).
Within a network, exactly one logon can hold a callsign.

Important (verified against live Hoppie): even `peek` / `ping` return
`error {callsign already in use}` when `from` is a callsign currently locked by a
**different** logon. Observer mode therefore only works as a second client next to
*your* aircraft client that shares this app’s logon — not for watching an arbitrary
third-party flight. Never silently steal the lock.

## Info requests (METAR / TAF / ATIS)

Station mode only (`type=inforeq`, `to=SERVER`). Reply is **inline** in the HTTP
response (no poll required):

```text
packet=metar EGLL
packet=taf EGLL
packet=vatatis EGLL_D_ATIS   # VATSIM departure D-ATIS (Fenix-style)
packet=vatatis EGLL_A_ATIS   # VATSIM arrival D-ATIS
packet=vatatis EGLL          # fallback when no split ATIS
packet=ivaoatis LFPG
packet=peatis KLAX
```

Example reply: `ok {acars info {EGLL 021350Z …}}` (type `info` stored as `inforeq`).

## PDC (pre-departure clearance)

Not a Hoppie type — send a **telex** to the delivery/ATC station:

```text
REQUEST PREDEP CLEARANCE
DLH4KM A320 TO EDDM
AT EDDF STAND A36
ATIS D
```

Clearance reply arrives asynchronously; poll afterward.

## Position reports

`type=position` with a plain-text packet (manual; no sim GPS in this app):

```text
LAT N5030.0
LON E00845.0
ALT FL360
TIME 1435Z
```

## CPDLC `/data2/` packets

Hoppie’s dedicated CPDLC documentation page has been intermittently unavailable.
This project implements the community wire form seen in message logs:

```text
/data2/{min}/{mrn}/{ra}/{text}
```

- `@` in CPDLC text is a presentation line break.
- Downlink replies (WILCO/ROGER/UNABLE/STANDBY) are built as
  `/data2/{ourMin}/{uplinkMin}/N/{REPLY}`.

Treat this as best-effort until confirmed against current Hoppie docs / operator guidance.

## Acceptable use

Before public/wide distribution, confirm polling and peek behavior with Hoppie
(`hoppie@hoppie.nl`). Do not tight-loop. Prefer 45–75s station polling; temporarily
~20s after send when expecting a reply. HTTP timeout 15s; no immediate retry after timeout.

## Secrets

Never log the full Hoppie logon code. It is stored encrypted at rest and masked in CLI status.
