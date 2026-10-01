import asyncio
import importlib
import os
import platform
import secrets
import shutil
import socket
import sys
import time
from collections import deque
from contextlib import nullcontext
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from studio.catalog import MODELS, get_model
from studio.downloads import DownloadManager, local_model, model_directory
from studio.engine import Engine, inference_installed
from studio.protocols import create_gateway
from studio.settings import Settings, load_settings, write_json

LANGUAGES = {
    "zh": "中文",
    "en": "英语",
    "ja": "日语",
    "ko": "韩语",
    "fr": "法语",
    "de": "德语",
    "es": "西班牙语",
    "ru": "俄语",
    "pt": "葡萄牙语",
    "ar": "阿拉伯语",
    "it": "意大利语",
    "vi": "越南语",
    "th": "泰语",
    "id": "印尼语",
}


class TranslationInput(BaseModel):
    text: str = Field(min_length=1, max_length=50000)
    source: str = Field(default="auto", max_length=80)
    target: str = Field(default="en", min_length=1, max_length=80)
    instruction: str = Field(default="", max_length=2000)


def translation_prompt(value: TranslationInput) -> str:
    source = "" if value.source == "auto" else LANGUAGES.get(value.source, value.source)
    target = LANGUAGES.get(value.target, value.target)
    prompt = f"请将以下{source}文本翻译为{target}，直接输出翻译结果，不要进行任何解释。"
    if value.instruction.strip():
        prompt += f"\n翻译要求：{value.instruction.strip()}"
    return prompt + "\n\n" + value.text.strip()


class LocalServer(uvicorn.Server):
    def capture_signals(self):
        # 控制服务拥有进程信号处理，公开 API 服务只负责自己的监听 socket。
        return nullcontext()


class Studio:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.settings = load_settings(data_dir)
        self.logs = deque(maxlen=150)
        self.engine = Engine()
        self.downloads = DownloadManager(self.log)
        self.runtime = {"status": "ready" if inference_installed() else "missing", "error": ""}
        self.deployment = {"status": "stopped", "model_id": "", "error": "", "since": None}
        self.translation = {"status": "idle", "text": "", "error": "", "elapsed": 0, "output_tokens": 0}
        self.gateway: LocalServer | None = None
        self.gateway_task: asyncio.Task | None = None
        self.operation_task: asyncio.Task | None = None
        self.translation_task: asyncio.Task | None = None
        self.install_task: asyncio.Task | None = None
        self.installer: asyncio.subprocess.Process | None = None
        self.log("本地控制服务已就绪，翻译文本仅在本机处理")

    def log(self, message: str, level: str = "info") -> None:
        self.logs.append({"time": time.time(), "level": level, "message": message})

    def snapshot(self) -> dict:
        directory = Path(self.settings.model_dir)
        while not directory.exists():
            directory = directory.parent
        memory = psutil.virtual_memory()
        return {
            "models": [{**model, "local": local_model(self.settings, model["id"])} for model in MODELS],
            "settings": self.settings.model_dump(),
            "download": self.downloads.state.copy(),
            "runtime": self.runtime.copy(),
            "deployment": self.deployment.copy(),
            "translation": self.translation.copy(),
            "logs": list(self.logs),
            "hardware": {
                "platform": platform.system(),
                "arch": platform.machine(),
                "memory_total": memory.total,
                "memory_available": memory.available,
                "disk_free": shutil.disk_usage(directory).free,
                "device": self.engine.device,
            },
            "stats": {
                "requests": self.engine.requests,
                "tokens_per_second": self.engine.last_speed,
                "busy": self.engine.active is not None,
            },
        }

    def save_settings(self, settings: Settings) -> None:
        if self.deployment["status"] in {"loading", "running", "stopping"} or self.downloads.busy:
            raise ValueError("请先停止服务并暂停下载，再修改设置")
        if self.runtime["status"] == "installing":
            raise ValueError("请等待推理依赖安装完成")
        if settings.max_tokens >= settings.max_context:
            raise ValueError("输出 token 上限必须小于上下文长度")
        Path(settings.model_dir).mkdir(parents=True, exist_ok=True)
        write_json(self.data_dir / "settings.json", settings.model_dump())
        self.settings = settings
        self.log("设置已保存，下次启动模型时生效")

    def install_runtime(self) -> None:
        if self.runtime["status"] == "installing":
            return
        if self.deployment["status"] not in {"stopped", "error"}:
            raise ValueError("请先停止模型再安装推理依赖")
        self.runtime = {"status": "installing", "error": ""}
        self.install_task = asyncio.create_task(self._install())

    async def _install(self):
        try:
            self.log("使用内嵌 Python 安装 PyTorch / Transformers，首次下载可能需要数分钟")
            uv = os.environ.get("INDEX_STUDIO_UV", "uv")
            requirements = Path(__file__).resolve().parent.parent / "requirements-inference.txt"
            self.installer = await asyncio.create_subprocess_exec(
                uv,
                "pip",
                "install",
                "--python",
                sys.executable,
                "--torch-backend",
                "auto",
                "--requirements",
                str(requirements),
                "--no-progress",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            tail = deque(maxlen=5)
            async for line in self.installer.stdout:
                message = line.decode("utf-8", errors="replace").strip()
                if message:
                    tail.append(message)
                    self.log(message)
            if await self.installer.wait() != 0:
                raise RuntimeError("推理依赖安装失败：" + " / ".join(tail))
            importlib.invalidate_caches()
            if not inference_installed():
                raise RuntimeError("安装结束，但未检测到完整推理依赖，请重试")
            self.runtime = {"status": "ready", "error": ""}
            self.log("推理环境已安装，可以启动模型")
        except Exception as error:
            self.runtime = {"status": "error", "error": str(error)}
            self.log(str(error), "error")
        finally:
            self.installer = None

    def start_model(self, model_id: str) -> None:
        if self.deployment["status"] in {"loading", "running", "stopping"}:
            raise ValueError("请先停止当前模型")
        if self.downloads.busy and self.downloads.state["model_id"] == model_id:
            raise ValueError("请等待此模型下载完成")
        if self.runtime["status"] != "ready":
            raise ValueError("请先安装推理依赖")
        if local_model(self.settings, model_id)["status"] != "ready":
            raise ValueError("模型尚未完整下载")
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind((self.settings.host, self.settings.port))
            listener.listen(128)
            listener.setblocking(False)
        except OSError as error:
            listener.close()
            raise ValueError(f"端口 {self.settings.port} 无法监听，请在设置中更换端口：{error}") from error
        self.deployment = {"status": "loading", "model_id": model_id, "error": "", "since": None}
        self.operation_task = asyncio.create_task(self._start(model_id, listener))

    async def _start(self, model_id: str, listener: socket.socket):
        try:
            self.log(f"正在加载 {get_model(model_id)['repo']}，首次加载可能较慢")
            await asyncio.to_thread(
                self.engine.load,
                model_directory(self.settings, model_id),
                get_model(model_id)["repo"],
                self.settings.device,
                self.settings.max_context,
            )
            self.gateway = LocalServer(
                uvicorn.Config(
                    create_gateway(self.engine, self.settings.model_copy()),
                    log_level="warning",
                    access_log=False,
                    lifespan="off",
                    timeout_graceful_shutdown=5,
                )
            )
            self.gateway_task = asyncio.create_task(self.gateway.serve(sockets=[listener]))
            while not self.gateway.started:
                if self.gateway_task.done():
                    await self.gateway_task
                    raise RuntimeError("API 服务未能启动")
                await asyncio.sleep(0.05)
            self.deployment.update(status="running", since=time.time())
            self.log(f"模型已启动，设备 {self.engine.device.upper()}，API 端口 {self.settings.port}")
        except Exception as error:
            listener.close()
            await asyncio.to_thread(self.engine.unload)
            self.deployment.update(status="error", error=str(error))
            self.log(f"启动失败：{error}", "error")

    def stop_model(self) -> None:
        if self.deployment["status"] == "loading":
            raise ValueError("模型正在加载，请等待加载结束；关闭应用可终止进程")
        if self.deployment["status"] in {"stopped", "stopping"}:
            return
        self.deployment["status"] = "stopping"
        self.operation_task = asyncio.create_task(self._stop())

    async def _stop(self):
        self.engine.cancel()
        if self.gateway:
            self.gateway.should_exit = True
        if self.gateway_task:
            await self.gateway_task
        await asyncio.to_thread(self.engine.unload)
        self.gateway = self.gateway_task = None
        self.deployment = {"status": "stopped", "model_id": "", "error": "", "since": None}
        self.log("服务已停止，模型已卸载")

    async def translate(self, value: TranslationInput) -> None:
        if self.deployment["status"] != "running":
            raise ValueError("请先在模型库中启动模型")
        if self.translation["status"] == "running":
            raise ValueError("翻译进行中，请先停止当前翻译")
        if not value.text.strip():
            raise ValueError("请输入需要翻译的文本")
        session = await self.engine.begin(
            [{"role": "user", "content": translation_prompt(value)}], self.settings.max_tokens
        )
        self.translation = {"status": "running", "text": "", "error": "", "elapsed": 0, "output_tokens": 0}

        async def collect():
            try:
                async for event in session.events():
                    if event["type"] == "delta":
                        self.translation["text"] += event["text"]
                    else:
                        self.translation.update(
                            status="cancelled" if event.get("cancelled") else "completed",
                            elapsed=event["elapsed"],
                            output_tokens=event["output_tokens"],
                        )
                        if event["finish_reason"] == "length":
                            self.translation["error"] = (
                                "已达到输出上限，译文可能不完整；可提高输出 token 上限后重试。"
                            )
            except Exception as error:
                self.translation.update(status="error", error=str(error))
                self.log(f"翻译失败：{error}", "error")

        self.translation_task = asyncio.create_task(collect())

    async def shutdown(self) -> None:
        self.downloads.pause()
        self.engine.cancel()
        if self.installer and self.installer.returncode is None:
            self.installer.terminate()
        if self.gateway:
            self.gateway.should_exit = True


def create_control(studio: Studio, token: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if not secrets.compare_digest(request.headers.get("x-studio-token", "").encode(), token.encode()):
            return JSONResponse({"detail": "控制接口未授权"}, 401)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(_request, error):
        message = "设置或输入参数无效" if isinstance(error, ValidationError) else str(error)
        return JSONResponse({"detail": message}, 400)

    @app.get("/status")
    async def status():
        return studio.snapshot()

    @app.put("/settings")
    async def settings(value: Settings):
        studio.save_settings(value)
        return {"ok": True}

    @app.post("/runtime/install")
    async def install():
        studio.install_runtime()
        return {"ok": True}

    @app.post("/download")
    async def download(request: Request):
        body = await request.json()
        model_id = body.get("model_id", "")
        if studio.deployment["model_id"] == model_id and studio.deployment["status"] in {
            "loading",
            "running",
            "stopping",
        }:
            raise HTTPException(409, "运行中的模型不可重新下载")
        studio.downloads.start(model_id, studio.settings)
        return {"ok": True}

    @app.post("/download/pause")
    async def pause():
        studio.downloads.pause()
        return {"ok": True}

    @app.post("/deploy/start")
    async def start(request: Request):
        studio.start_model((await request.json()).get("model_id", ""))
        return {"ok": True}

    @app.post("/deploy/stop")
    async def stop():
        studio.stop_model()
        return {"ok": True}

    @app.post("/translate")
    async def translate(value: TranslationInput):
        await studio.translate(value)
        return {"ok": True}

    @app.post("/translate/cancel")
    async def cancel():
        if studio.translation["status"] == "running":
            studio.engine.cancel()
        return {"ok": True}

    return app
