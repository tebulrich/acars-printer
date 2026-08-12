/**
 * Build the frozen Python bridge, stage it for Tauri, then build the desktop app.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();

function run(command, args) {
  // Avoid shell:true — paths with spaces (e.g. "Tebin Ulrich") break cmd.exe.
  const result = spawnSync(command, args, {
    cwd: root,
    stdio: "inherit",
    shell: false,
    env: process.env,
  });
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function runShell(line) {
  const result = spawnSync(line, {
    cwd: root,
    stdio: "inherit",
    shell: true,
    env: process.env,
  });
  if (result.error) {
    console.error(result.error);
    process.exit(1);
  }
  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

const venvPython = join(root, ".venv", "Scripts", "python.exe");

console.log("=== Building Python bridge sidecar ===");
if (existsSync(venvPython)) {
  run(venvPython, [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    "packaging/acars-bridge-sidecar.spec",
  ]);
} else {
  // Fallback when .venv is missing; uv on PATH, args stay separate (no path spaces).
  run("uv", [
    "run",
    "pyinstaller",
    "--noconfirm",
    "--clean",
    "packaging/acars-bridge-sidecar.spec",
  ]);
}

run(process.execPath, [join(root, "scripts", "stage-sidecar.mjs")]);

console.log("=== Building Tauri app ===");
// npx.cmd needs a shell on Windows; keep the line quoted as one string.
runShell("npx tauri build");
run(process.execPath, [join(root, "scripts", "copy-release.mjs")]);
