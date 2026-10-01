import hashlib
import json
import re
import shutil
import threading
import time
from pathlib import Path

import httpx

from studio.catalog import RemoteFile, fetch_manifest, get_model, serialize_manifest
from studio.settings import Settings, write_json


class DownloadPaused(Exception):
    pass


def file_matches(path: Path, file: RemoteFile) -> bool:
    if not path.is_file() or path.stat().st_size != file.size:
        return False
    digest = hashlib.sha256() if file.sha256 else hashlib.sha1()
    if not file.sha256:
        digest.update(f"blob {file.size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == file.identity


def partial_path(path: Path, file: RemoteFile) -> Path:
    return path.with_name(path.name + "." + file.identity[:16] + ".part")


def download_file(
    client: httpx.Client, file: RemoteFile, directory: Path, cancel: threading.Event, progress
) -> None:
    path = directory / file.path
    path.parent.mkdir(parents=True, exist_ok=True)
    if file_matches(path, file):
        progress(file.size)
        return
    partial = partial_path(path, file)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > file.size:
        offset = 0
    if offset == file.size and file_matches(partial, file):
        partial.replace(path)
        progress(file.size)
        return
    if offset == file.size:
        offset = 0
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with client.stream("GET", file.url, headers=headers) as response:
        response.raise_for_status()
        if response.status_code == 206:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
            if not match or int(match[1]) != offset or int(match[3]) != file.size:
                raise ValueError("下载源返回了错误的续传范围，请切换下载源")
        elif response.status_code == 200:
            # 镜像可能忽略 Range；必须从零写入，不能追加完整文件。
            offset = 0
        else:
            raise ValueError(f"下载源返回了不支持的状态：{response.status_code}")
        with partial.open("ab" if offset else "wb") as stream:
            progress(offset)
            for chunk in response.iter_bytes(1024 * 1024):
                if cancel.is_set():
                    raise DownloadPaused()
                stream.write(chunk)
                offset += len(chunk)
                if offset > file.size:
                    raise ValueError("下载内容超出预期大小")
                progress(offset)
    if not file_matches(partial, file):
        raise ValueError("文件校验失败；再次下载会重新获取损坏的文件")
    partial.replace(path)


def model_directory(settings: Settings, model_id: str) -> Path:
    return Path(settings.model_dir) / get_model(model_id)["repo"].split("/")[1]


def local_model(settings: Settings, model_id: str) -> dict:
    directory = model_directory(settings, model_id)
    manifest = directory / ".manifest.json"
    if not manifest.exists():
        return {"status": "missing", "downloaded": 0, "total": 0}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        files = [RemoteFile(**file) for file in data["files"]]
        marker = directory / ".complete.json"
        verified = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
        complete = bool(files) and all(
            (directory / f.path).is_file() and (directory / f.path).stat().st_size == f.size for f in files
        )
        complete = complete and verified.get("files") == {f.path: f.identity for f in files}
        downloaded = sum(
            min(f.size, (directory / f.path).stat().st_size)
            if (directory / f.path).exists()
            else min(f.size, partial_path(directory / f.path, f).stat().st_size)
            if partial_path(directory / f.path, f).exists()
            else 0
            for f in files
        )
        return {
            "status": "ready" if complete else "partial",
            "downloaded": downloaded,
            "total": sum(f.size for f in files),
            "source": data["source"],
        }
    except (ValueError, KeyError, OSError, TypeError):
        return {"status": "partial", "downloaded": 0, "total": 0}


class DownloadManager:
    def __init__(self, log):
        self.log = log
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self.state = {
            "status": "idle",
            "model_id": "",
            "downloaded": 0,
            "total": 0,
            "speed": 0,
            "file": "",
            "error": "",
        }

    @property
    def busy(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, model_id: str, settings: Settings) -> None:
        if self.busy:
            raise ValueError("已有下载任务，请先暂停当前任务")
        get_model(model_id)
        self.cancel.clear()
        self.state = {
            "status": "preparing",
            "model_id": model_id,
            "downloaded": 0,
            "total": 0,
            "speed": 0,
            "file": "正在读取文件列表",
            "error": "",
        }
        self.thread = threading.Thread(target=self._run, args=(model_id, settings.model_copy()), daemon=True)
        self.thread.start()

    def pause(self) -> None:
        self.cancel.set()
        if self.busy:
            self.state["status"] = "pausing"

    def _run(self, model_id: str, settings: Settings) -> None:
        try:
            directory = model_directory(settings, model_id)
            directory.mkdir(parents=True, exist_ok=True)
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30, connect=15)) as client:
                files = fetch_manifest(client, model_id, settings)
                total = sum(f.size for f in files)
                existing = sum(
                    min(f.size, (directory / f.path).stat().st_size)
                    if (directory / f.path).exists()
                    else min(f.size, partial_path(directory / f.path, f).stat().st_size)
                    if partial_path(directory / f.path, f).exists()
                    else 0
                    for f in files
                )
                if shutil.disk_usage(directory).free < total - existing + 512 * 1024 * 1024:
                    raise ValueError("磁盘空间不足：请在设置中选择空间更充足的模型目录")
                write_json(
                    directory / ".manifest.json",
                    {"source": settings.source, "files": serialize_manifest(files)},
                )
                self.state.update(status="downloading", total=total)
                self.log(f"开始下载 {get_model(model_id)['repo']}，来源 {settings.source}")
                done = 0
                for file in files:
                    if self.cancel.is_set():
                        raise DownloadPaused()
                    self.state["file"] = file.path
                    sample_time, sample_bytes = time.monotonic(), None

                    def progress(value, completed_bytes=done):
                        nonlocal sample_time, sample_bytes
                        now = time.monotonic()
                        self.state["downloaded"] = completed_bytes + value
                        if sample_bytes is None:
                            sample_time, sample_bytes = now, value
                            return
                        if now - sample_time >= 0.5:
                            self.state["speed"] = max(0, (value - sample_bytes) / (now - sample_time))
                            sample_time, sample_bytes = now, value

                    for attempt in range(3):
                        try:
                            download_file(client, file, directory, self.cancel, progress)
                            break
                        except (httpx.TransportError, httpx.HTTPStatusError):
                            if attempt == 2:
                                raise
                            self.log(f"连接中断，正在重试 {file.path} ({attempt + 1}/2)")
                            if self.cancel.wait(2**attempt):
                                raise DownloadPaused() from None
                    done += file.size
                write_json(
                    directory / ".complete.json",
                    {
                        "model_id": model_id,
                        "verified_at": time.time(),
                        "files": {f.path: f.identity for f in files},
                    },
                )
                self.state.update(status="completed", downloaded=total, speed=0)
                self.log("模型下载与校验完成，可以启动部署")
        except DownloadPaused:
            self.state.update(status="paused", speed=0)
            self.log("下载已暂停，已保留文件，可选择同源或兼容源续传")
        except Exception as error:
            self.state.update(status="error", error=str(error), speed=0)
            self.log(f"下载失败：{error}", "error")
