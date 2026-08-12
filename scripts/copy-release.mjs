import {
  copyFileSync,
  mkdirSync,
  existsSync,
  readdirSync,
  unlinkSync,
  statSync,
  readFileSync,
} from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const releaseDir = join(root, "src-tauri", "target", "release");
const outDir = join(root, "dist");
mkdirSync(outDir, { recursive: true });

const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const version = pkg.version || "0.0.0";

const exe = join(releaseDir, "acars-print-bridge.exe");
if (!existsSync(exe)) {
  console.error("Missing release EXE:", exe);
  process.exit(1);
}

const destExe = join(outDir, "ACARS-Print-Bridge.exe");
const destVersioned = join(
  outDir,
  `ACARS-Print-Bridge-${version}-windows-x64.exe`,
);

try {
  copyFileSync(exe, destExe);
  copyFileSync(exe, destVersioned);
} catch (err) {
  console.error(
    "Could not write dist/ACARS-Print-Bridge.exe — close the running app and retry.",
  );
  console.error(String(err));
  process.exit(1);
}
console.log("Copied", exe, "-> dist/ACARS-Print-Bridge.exe");
console.log("Copied portable", destVersioned);

// Do not ship a peer acars-bridge.exe — it is embedded inside the main EXE.
for (const name of readdirSync(outDir)) {
  if (
    name === "acars-bridge.exe" ||
    (name.startsWith("ACARS-Print-Bridge-") && name.endsWith(".zip"))
  ) {
    try {
      unlinkSync(join(outDir, name));
      console.log("Removed leftover", name);
    } catch {
      /* ignore locked leftovers */
    }
  }
}

const nsisDir = join(releaseDir, "bundle", "nsis");
if (existsSync(nsisDir)) {
  const setups = readdirSync(nsisDir)
    .filter((name) => name.endsWith("-setup.exe"))
    .sort((a, b) => {
      const ta = statSync(join(nsisDir, a)).mtimeMs;
      const tb = statSync(join(nsisDir, b)).mtimeMs;
      return ta - tb;
    });
  const latest = setups.at(-1);
  if (latest) {
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
