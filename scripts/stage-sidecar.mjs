/**
 * Stage the PyInstaller bridge binary for embedding into the Tauri shell.
 *
 * Expects: build/sidecar-dist/acars-bridge.exe (never under dist/)
 * Writes:  src-tauri/embedded/acars-bridge.exe
 *
 * The desktop EXE includes these bytes and extracts them under LocalAppData
 * at runtime — end users only download / run one app.
 */
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const srcCandidates = [
  join(root, "build", "sidecar-dist", "acars-bridge.exe"),
  join(root, "build", "sidecar-dist", "acars-bridge"),
  // Legacy path from older builds — stage then delete so dist stays one-file.
  join(root, "dist", "acars-bridge.exe"),
  join(root, "dist", "acars-bridge"),
];
const src = srcCandidates.find((p) => existsSync(p));
if (!src) {
  console.error(
    "Missing PyInstaller bridge at build/sidecar-dist/acars-bridge.exe — run:\n" +
      "  npm run build:exe   (or pyinstaller with --distpath build/sidecar-dist)",
  );
  process.exit(1);
}

const outDir = join(root, "src-tauri", "embedded");
mkdirSync(outDir, { recursive: true });
const dest = join(outDir, "acars-bridge.exe");
copyFileSync(src, dest);
writeFileSync(join(outDir, ".gitkeep"), "");

// Never leave a peer EXE in dist/ for users to confuse with the product.
for (const leftover of [
  join(root, "dist", "acars-bridge.exe"),
  join(root, "dist", "acars-bridge"),
]) {
  if (existsSync(leftover)) {
    try {
      unlinkSync(leftover);
      console.log("Removed leftover", leftover);
    } catch {
      /* ignore locked */
    }
  }
}

console.log("Staged embedded bridge:", dest);
