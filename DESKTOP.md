# Desktop (Tauri)

ACARS Print Bridge desktop UI matches **hangar-link** / **vmr-wizard**:

- Tauri 2 + React 19 + Vite 7 + Tailwind v4 + TypeScript
- Python engine stays in `src/acars_bridge/`
- Long-lived NDJSON sidecar: `python -m acars_bridge.bridge serve`

## Release

```powershell
uv sync --group dev
npm install
npm run build:exe
```

This builds a frozen Python bridge, **embeds it inside** `ACARS-Print-Bridge.exe`,
and copies a single portable EXE (+ NSIS setup) into `dist/`. Users only run one
app; the helper is extracted under `%LOCALAPPDATA%\acars-bridge\sidecar\` on first
launch.

On first launch the app writes `acars-print-bridge.log` next to the EXE (startup
+ bridge debug). Send that file when reporting crashes.

Env overrides (dev):

- `ACARS_BRIDGE_PYTHON` — interpreter for the sidecar when no embedded bridge
- `ACARS_BRIDGE_ROOT` — project root (package + `src/acars_bridge`)
- `ACARS_BRIDGE_DATA_DIR` — alternate data directory (also skips single-instance lock in serve)
- `ACARS_BRIDGE_EXE_LOG` — force support log path (normally set by the desktop shell)
- `ACARS_BRIDGE_FAKE_PRINTER=1` — force fake printer in serve

## Dev

```powershell
uv sync --group dev
npm install
npm run tauri -- dev
```

Dev still uses `python -m acars_bridge.bridge serve` from the project venv when
no embedded bridge is present.
