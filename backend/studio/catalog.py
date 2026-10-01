import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from studio.settings import Settings

MODELS = json.loads(Path(__file__).with_name("models.json").read_text(encoding="utf-8"))


def get_model(model_id: str) -> dict:
    for model in MODELS:
        if model["id"] == model_id:
            return model
    raise ValueError("未知的翻译模型")


@dataclass
class RemoteFile:
    path: str
    size: int
    url: str
    sha256: str = ""
    git_sha1: str = ""

    @property
    def identity(self) -> str:
        # 不同源只有相同的内容哈希才能复用下载片段。
        return self.sha256 or self.git_sha1


def safe_model_file(path: str) -> bool:
    candidate = PurePosixPath(path)
    if not path or candidate.is_absolute() or ".." in candidate.parts or "\\" in path or ":" in path:
        raise ValueError("模型仓库包含不安全的文件路径")
    if any(part.startswith(".") for part in candidate.parts):
        return False
    return candidate.suffix in {".safetensors", ".json", ".jinja", ".model"} or candidate.name in {
        "merges.txt",
        "vocab.txt",
        "LICENSE",
        "LICENSE.txt",
        "README.md",
    }


def fetch_manifest(client: httpx.Client, model_id: str, settings: Settings) -> list[RemoteFile]:
    repo = get_model(model_id)["repo"]
    files: list[RemoteFile] = []
    if settings.source == "modelscope":
        base = f"https://modelscope.cn/api/v1/models/{repo}/repo/files"
        response = client.get(base, params={"Revision": "master", "Recursive": "true"})
        response.raise_for_status()
        payload = response.json()
        if not payload.get("Success"):
            raise ValueError("ModelScope 未能返回文件列表，请切换下载源后重试")
        for entry in payload["Data"]["Files"]:
            if entry["Type"] == "blob" and safe_model_file(entry["Path"]):
                # 每个文件固定到其内容提交，避免下载中途遇到上游更新。
                url = str(
                    httpx.URL(
                        f"https://modelscope.cn/api/v1/models/{repo}/repo",
                        params={"Revision": entry["Revision"], "FilePath": entry["Path"]},
                    )
                )
                files.append(RemoteFile(entry["Path"], entry["Size"], url, entry["Sha256"]))
    else:
        endpoint = {
            "huggingface": "https://huggingface.co",
            "hf-mirror": "https://hf-mirror.com",
            "custom": settings.mirror_url,
        }[settings.source]
        response = client.get(f"{endpoint}/api/models/{repo}", params={"blobs": "true"})
        response.raise_for_status()
        payload = response.json()
        revision = payload["sha"]
        for entry in payload["siblings"]:
            if safe_model_file(entry["rfilename"]):
                lfs = entry.get("lfs", {})
                files.append(
                    RemoteFile(
                        entry["rfilename"],
                        entry["size"],
                        f"{endpoint}/{repo}/resolve/{quote(revision, safe='')}/{quote(entry['rfilename'])}",
                        lfs.get("sha256", ""),
                        "" if lfs else entry.get("blobId", ""),
                    )
                )
    if not files or not any(f.path.endswith(".safetensors") for f in files):
        raise ValueError("此下载源尚未提供完整模型权重（只有配置或索引）。请切换源或等待官方补齐。")
    if not all(
        isinstance(f.size, int)
        and f.size > 0
        and re.fullmatch(r"[0-9a-f]{64}" if f.sha256 else r"[0-9a-f]{40}", f.identity)
        for f in files
    ):
        raise ValueError("下载源缺少文件大小或校验值，无法安全续传")
    names = {f.path for f in files}
    if not {"config.json", "tokenizer_config.json"} <= names:
        raise ValueError("模型仓库缺少必要配置")
    for entry in files:
        if entry.path.endswith(".safetensors.index.json"):
            response = client.get(entry.url)
            response.raise_for_status()
            shards = set(response.json()["weight_map"].values())
            if not shards or not shards <= names:
                raise ValueError("上游权重分片不完整，请等待发布完成或切换下载源")
    return files


def serialize_manifest(files: list[RemoteFile]) -> list[dict]:
    return [asdict(file) for file in files]
