/**
 * Stage the PyInstaller bridge binary for embedding into the Tauri shell.
 *
 * Expects: dist/acars-bridge.exe (from packaging/acars-bridge-sidecar.spec)
 * Writes:  src-tauri/embedded/acars-bridge.exe
 *
 * The desktop EXE includes these bytes and extracts them under LocalAppData
 * at runtime — end users only download / run one app.
 */
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const srcCandidates = [
  join(root, "dist", "acars-bridge.exe"),
  join(root, "dist", "acars-bridge"),
];
const src = srcCandidates.find((p) => existsSync(p));
if (!src) {
  console.error(
    "Missing PyInstaller bridge at dist/acars-bridge.exe — run:\n" +
      "  uv run pyinstaller --noconfirm --clean packaging/acars-bridge-sidecar.spec",
  );
  process.exit(1);
}

const outDir = join(root, "src-tauri", "embedded");
mkdirSync(outDir, { recursive: true });
const dest = join(outDir, "acars-bridge.exe");
copyFileSync(src, dest);
writeFileSync(join(outDir, ".gitkeep"), "");
console.log("Staged embedded bridge:", dest);
