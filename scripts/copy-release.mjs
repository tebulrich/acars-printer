import { copyFileSync, mkdirSync, existsSync, readdirSync, unlinkSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const releaseDir = join(root, "src-tauri", "target", "release");
const outDir = join(root, "dist");
mkdirSync(outDir, { recursive: true });

const exe = join(releaseDir, "acars-print-bridge.exe");
if (!existsSync(exe)) {
  console.error("Missing release EXE:", exe);
  process.exit(1);
}

const destExe = join(outDir, "ACARS-Print-Bridge.exe");
try {
  copyFileSync(exe, destExe);
} catch (err) {
  console.error(
    "Could not write dist/ACARS-Print-Bridge.exe — close the running app and retry.",
  );
  console.error(String(err));
  process.exit(1);
}
console.log("Copied", exe, "-> dist/ACARS-Print-Bridge.exe");

const nsisDir = join(releaseDir, "bundle", "nsis");
if (existsSync(nsisDir)) {
  const setups = readdirSync(nsisDir)
    .filter((name) => name.endsWith("-setup.exe"))
    .sort();
  const latest = setups.at(-1);
  if (latest) {
    // Drop older installers so dist/ only keeps the current release setup.
    for (const name of readdirSync(outDir)) {
      if (name.endsWith("-setup.exe") && name !== latest) {
        try {
          unlinkSync(join(outDir, name));
        } catch {
          /* ignore locked leftovers */
        }
      }
    }
    copyFileSync(join(nsisDir, latest), join(outDir, latest));
    console.log("Copied installer", latest);
  }
}
