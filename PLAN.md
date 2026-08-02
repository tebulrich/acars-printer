# ACARS Print Bridge — Plan

Python greenfield standalone Hoppie client. See the Cursor plan for product detail.

## Stack

- Python 3.12+, uv, pytest, ruff, typer, httpx, python-escpos, cryptography

## Mode

**Local tap**: redirect Hoppie through this app, forward to the real server,
print whatever the aircraft receives (including inline weather). No second
Hoppie logon. Requires Administrator on Windows (hosts + ports 80/443).

## Phase 1 checklist

- [x] Wipe PHP/Laravel prototype
- [x] Scaffold Python package
- [x] Hoppie client + parser + CPDLC + Station/Observer
- [x] SQLite + fingerprint dedupe + printing
- [x] Typer CLI
- [x] Fixture tests + docs

## Phase 2 checklist

- [x] CustomTkinter desktop UI (messages, replies, settings, poller)
- [x] Background poller + notifications hook
- [x] `acars-bridge ui` entrypoint

## Later

- [ ] Phase 3 reliability / inforeq / tray polish
- [ ] Phase 4 packaging
