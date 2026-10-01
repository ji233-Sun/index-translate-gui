import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import {
  chmod,
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const uvVersion = "0.10.9";
const pythonVersion = "3.12.12";
const platforms = {
  "darwin-arm64": "aarch64-apple-darwin",
  "win32-x64": "x86_64-pc-windows-msvc",
  "linux-x64": "x86_64-unknown-linux-gnu",
};
const target = platforms[`${process.platform}-${process.arch}`];
if (!target)
  throw new Error(
    `暂不支持 ${process.platform}/${process.arch}；macOS 请使用 Apple Silicon`,
  );
const binaryDir = join(root, "src-tauri", "binaries");
const binary = join(
  binaryDir,
  `index-studio-uv-${target}${process.platform === "win32" ? ".exe" : ""}`,
);
const pythonDir = join(root, "src-tauri", "python");
const stage = await mkdtemp(join(tmpdir(), "index-studio-build-"));

function run(command, args) {
  execFileSync(command, args, {
    cwd: root,
    stdio: "inherit",
    windowsHide: true,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
}

async function fetchBytes(url) {
  const response = await fetch(url, { signal: AbortSignal.timeout(180_000) });
  if (!response.ok) throw new Error(`下载失败 ${response.status}: ${url}`);
  return Buffer.from(await response.arrayBuffer());
}

async function findFile(directory, filename) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.name === filename && entry.isFile()) return path;
    if (entry.isDirectory()) {
      const nested = await findFile(path, filename);
      if (nested) return nested;
    }
  }
}

try {
  await mkdir(binaryDir, { recursive: true });
  try {
    const version = execFileSync(binary, ["--version"], {
      encoding: "utf8",
      windowsHide: true,
    });
    if (!version.startsWith(`uv ${uvVersion} `))
      throw new Error("uv 版本不匹配");
  } catch {
    const extension = process.platform === "win32" ? "zip" : "tar.gz";
    const filename = `uv-${target}.${extension}`;
    const base = `https://github.com/astral-sh/uv/releases/download/${uvVersion}/${filename}`;
    console.log(`下载内嵌 uv ${uvVersion} (${target})`);
    const bytes = await fetchBytes(base);
    const checksum = (await fetchBytes(`${base}.sha256`))
      .toString("utf8")
      .trim()
      .split(/\s+/)[0];
    if (createHash("sha256").update(bytes).digest("hex") !== checksum)
      throw new Error("uv 校验失败");
    const archive = join(stage, filename);
    await writeFile(archive, bytes);
    if (process.platform === "win32") {
      const expandScript = join(stage, "expand.ps1");
      await writeFile(
        expandScript,
        "param([string]$Archive, [string]$Output)\nExpand-Archive -LiteralPath $Archive -DestinationPath $Output\n",
      );
      run("powershell.exe", [
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        expandScript,
        archive,
        stage,
      ]);
    } else {
      run("tar", ["-xzf", archive, "-C", stage]);
    }
    const extracted = await findFile(
      stage,
      process.platform === "win32" ? "uv.exe" : "uv",
    );
    if (!extracted) throw new Error("uv 归档缺少可执行文件");
    await copyFile(extracted, binary);
    if (process.platform !== "win32") await chmod(binary, 0o755);
  }
  console.log(`准备内嵌 Python ${pythonVersion}，不会修改系统 Python`);
  run(binary, [
    "python",
    "install",
    pythonVersion,
    "--install-dir",
    pythonDir,
    "--no-bin",
    "--no-registry",
  ]);
  const installations = (await readdir(pythonDir)).filter((name) =>
    name.startsWith(`cpython-${pythonVersion}-`),
  );
  if (installations.length !== 1) throw new Error("内嵌 Python 目录不唯一");
  const interpreter = join(
    pythonDir,
    installations[0],
    process.platform === "win32" ? "python.exe" : "bin/python3.12",
  );
  const requirements = join(stage, "requirements.txt");
  run(binary, [
    "export",
    "--project",
    join(root, "backend"),
    "--frozen",
    "--no-dev",
    "--no-emit-project",
    "--output-file",
    requirements,
    "--quiet",
  ]);
  // 仅修改 src-tauri/python 内新下载的打包副本；uv 默认会保护它的基础环境。
  run(binary, [
    "pip",
    "install",
    "--python",
    interpreter,
    "--requirements",
    requirements,
    "--no-python-downloads",
    "--break-system-packages",
  ]);
  run(interpreter, [
    "-c",
    'import fastapi, uvicorn, httpx, psutil; print("Embedded Python and management dependencies OK")',
  ]);
  const lockHash = createHash("sha256")
    .update(await readFile(join(root, "backend", "uv.lock")))
    .digest("hex");
  await writeFile(
    join(pythonDir, "runtime.json"),
    JSON.stringify(
      { version: pythonVersion, directory: installations[0], lockHash },
      null,
      2,
    ),
  );
  console.log(
    "内嵌运行时已准备完成。安装包首次启动无需联网安装 Python 或管理依赖。",
  );
} finally {
  await rm(stage, { recursive: true, force: true });
}
