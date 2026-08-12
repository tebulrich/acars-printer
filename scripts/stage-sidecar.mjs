/**
 * Stage the PyInstaller bridge sidecar for Tauri externalBin.
 *
 * Expects: dist/acars-bridge.exe (from packaging/acars-bridge-sidecar.spec)
 * Writes:  src-tauri/binaries/acars-bridge-<host-tuple>.exe
 */
import { execSync } from "node:child_process";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  unlinkSync,
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
    "Missing PyInstaller sidecar at dist/acars-bridge.exe — run:\n" +
      "  uv run pyinstaller --noconfirm --clean packaging/acars-bridge-sidecar.spec",
  );
  process.exit(1);
}

const triple = execSync("rustc --print host-tuple", { encoding: "utf8" }).trim();
if (!triple) {
  console.error("Could not read rustc host-tuple");
  process.exit(1);
}

const outDir = join(root, "src-tauri", "binaries");
mkdirSync(outDir, { recursive: true });
const dest = join(outDir, `acars-bridge-${triple}.exe`);

for (const name of readdirSync(outDir)) {
  if (name.startsWith("acars-bridge-") && name.endsWith(".exe") && name !== `acars-bridge-${triple}.exe`) {
    try {
      unlinkSync(join(outDir, name));
    } catch {
      /* ignore */
    }
  }
}

copyFileSync(src, dest);
console.log("Staged sidecar:", dest);
