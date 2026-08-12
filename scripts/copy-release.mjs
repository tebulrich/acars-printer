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
import { spawnSync } from "node:child_process";

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

// Sidecar must sit next to the portable EXE (NSIS already bundles it).
const sidecarNames = ["acars-bridge.exe", "acars-bridge"];
let sidecarDest = null;
for (const name of sidecarNames) {
  const src = join(releaseDir, name);
  if (!existsSync(src)) continue;
  const dest = join(outDir, name.endsWith(".exe") ? name : `${name}.exe`);
  try {
    copyFileSync(src, dest);
    console.log("Copied sidecar", src, "->", dest);
    sidecarDest = dest;
    break;
  } catch (err) {
    console.error("Could not copy sidecar:", err);
    process.exit(1);
  }
}
if (!sidecarDest) {
  // Fall back to staged binaries/ folder (pre-bundle name with target triple).
  const binDir = join(root, "src-tauri", "binaries");
  if (existsSync(binDir)) {
    for (const name of readdirSync(binDir)) {
      if (!name.startsWith("acars-bridge-") || !name.endsWith(".exe")) continue;
      const src = join(binDir, name);
      const dest = join(outDir, "acars-bridge.exe");
      copyFileSync(src, dest);
      console.log("Copied staged sidecar", src, "->", dest);
      sidecarDest = dest;
      break;
    }
  }
}
if (!sidecarDest) {
  console.error(
    "Missing acars-bridge.exe sidecar next to the release EXE. Run npm run build:exe (builds sidecar first).",
  );
  process.exit(1);
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

// Portable zip: both EXEs together (single EXE alone cannot start).
const zipName = `ACARS-Print-Bridge-${version}-windows-x64.zip`;
const zipPath = join(outDir, zipName);
const q = (p) => `'${String(p).replace(/'/g, "''")}'`;
const ps = `
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath ${q(zipPath)}) { Remove-Item -LiteralPath ${q(zipPath)} -Force }
Compress-Archive -LiteralPath @(${q(destExe)}, ${q(sidecarDest)}) -DestinationPath ${q(zipPath)} -Force
`;
const result = spawnSync("powershell.exe", ["-NoProfile", "-Command", ps], {
  encoding: "utf8",
});
if (result.status !== 0) {
  console.error("Could not create portable zip:", result.stderr || result.stdout);
  process.exit(1);
}
console.log("Created portable zip", zipPath);
