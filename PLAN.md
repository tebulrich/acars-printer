# ACARS Print Bridge — Plan

Python greenfield standalone Hoppie client. See the Cursor plan for product detail.

## Stack

- Python 3.12+, uv, pytest, ruff, typer, httpx, python-escpos, cryptography

## Modes

| Mode | Transport | Send | Use |
|------|-----------|------|-----|
| Station | `poll` | Yes | Standalone |
| Observer | `peek` | No | Beside PMDG/TFDi/etc. |

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
