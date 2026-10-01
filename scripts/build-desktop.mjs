import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { delimiter, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const env = { ...process.env };
if (process.platform === "linux") {
  const pythonRoot = join(root, "src-tauri", "python");
  const runtime = JSON.parse(
    readFileSync(join(pythonRoot, "runtime.json"), "utf8"),
  );
  // linuxdeploy 扫描 Python 扩展时，需要找到解释器自带的 Tcl/Tk 等动态库。
  env.LD_LIBRARY_PATH = [
    join(pythonRoot, runtime.directory, "lib"),
    env.LD_LIBRARY_PATH,
  ]
    .filter(Boolean)
    .join(delimiter);
}
const result = spawnSync(
  process.execPath,
  [
    join(root, "node_modules", "@tauri-apps", "cli", "tauri.js"),
    "build",
    ...process.argv.slice(2),
  ],
  { cwd: root, stdio: "inherit", env, windowsHide: true },
);
if (result.error) throw result.error;
process.exit(result.status ?? 1);
