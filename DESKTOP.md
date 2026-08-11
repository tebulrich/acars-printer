# Desktop (Tauri)

ACARS Print Bridge desktop UI matches **hangar-link** / **vmr-wizard**:

- Tauri 2 + React 19 + Vite 7 + Tailwind v4 + TypeScript
- Python engine stays in `src/acars_bridge/`
- Long-lived NDJSON sidecar: `python -m acars_bridge.bridge serve`

## Dev

```powershell
uv sync --group dev
npm install
npm run tauri -- dev
```

Env overrides:

- `ACARS_BRIDGE_PYTHON` — interpreter for the sidecar
- `ACARS_BRIDGE_ROOT` — project root (package + `src/acars_bridge`)
- `ACARS_BRIDGE_DATA_DIR` — alternate data directory (also skips single-instance lock in serve)
- `ACARS_BRIDGE_FAKE_PRINTER=1` — force fake printer in serve

## Release

```powershell
npm run build:exe
```

Artifacts land in `dist/`.
