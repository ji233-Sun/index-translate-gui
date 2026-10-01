import json
import os
import secrets
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class Settings(BaseModel):
    port: int = Field(default=8765, ge=1024, le=65535)
    host: Literal["127.0.0.1", "0.0.0.0"] = "127.0.0.1"
    api_key: str = Field(
        default_factory=lambda: "it-" + secrets.token_urlsafe(24), min_length=16, max_length=256
    )
    model_dir: str
    source: Literal["modelscope", "huggingface", "hf-mirror", "custom"] = "modelscope"
    mirror_url: str = "https://hf-mirror.com"
    python_index_url: str = "https://pypi.org/simple"
    torch_auto_backend: bool = True
    device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
    max_context: int = Field(default=4096, ge=512, le=32768)
    max_tokens: int = Field(default=1024, ge=1, le=8192)

    @field_validator("api_key")
    @classmethod
    def printable_key(cls, value: str) -> str:
        if not value.isascii() or any(c.isspace() or not c.isprintable() for c in value):
            raise ValueError("访问密钥只能包含无空格的 ASCII 可打印字符")
        return value

    @field_validator("model_dir")
    @classmethod
    def absolute_directory(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("模型目录必须是绝对路径")
        return str(path.resolve())

    @field_validator("mirror_url")
    @classmethod
    def https_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise ValueError("镜像地址必须是 HTTPS 域名，例如 https://hf-mirror.com")
        return value.rstrip("/")

    @field_validator("python_index_url")
    @classmethod
    def python_package_index(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or any(char.isspace() or not char.isprintable() for char in value)
        ):
            raise ValueError("Python 安装源须为不含凭据、参数或空格的 HTTPS Simple API 地址")
        # 读取端口会校验非法端口值，路径保留以支持 /simple 等索引端点。
        _ = parsed.port
        return value.rstrip("/")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


def load_settings(data_dir: Path) -> Settings:
    path = data_dir / "settings.json"
    if path.exists():
        return Settings.model_validate_json(path.read_text(encoding="utf-8"))
    settings = Settings(model_dir=str(data_dir / "models"))
    write_json(path, settings.model_dump())
    return settings
