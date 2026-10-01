import asyncio
import gc
import importlib.util
import os
import threading
import time
from pathlib import Path

from fastapi import HTTPException


def inference_installed() -> bool:
    importlib.invalidate_caches()
    return all(importlib.util.find_spec(name) is not None for name in ("torch", "transformers", "accelerate"))


class StopFilter:
    """保留可能跨 token 的停止字符串前缀，防止将停止标记发给客户端。"""

    def __init__(self, stops: list[str]):
        self.stops = stops
        self.pending = ""
        self.stopped = False
        self.stop_sequence = None

    def feed(self, text: str, final: bool = False) -> str:
        if self.stopped:
            return ""
        self.pending += text
        positions = [self.pending.find(stop) for stop in self.stops if stop in self.pending]
        if positions:
            position = min(positions)
            self.stop_sequence = next(stop for stop in self.stops if self.pending.startswith(stop, position))
            result = self.pending[:position]
            self.pending = ""
            self.stopped = True
            return result
        keep = 0
        if not final:
            for stop in self.stops:
                for length in range(1, min(len(stop), len(self.pending) + 1)):
                    if self.pending.endswith(stop[:length]):
                        keep = max(keep, length)
        result = self.pending[:-keep] if keep else self.pending
        self.pending = self.pending[-keep:] if keep else ""
        return result


class Generation:
    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.cancel = threading.Event()
        self.input_tokens = 0

    async def events(self):
        try:
            while True:
                event = await self.queue.get()
                if event["type"] == "error":
                    raise RuntimeError(event["message"])
                yield event
                if event["type"] == "done":
                    break
        finally:
            self.cancel.set()


class Engine:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.model_id = ""
        self.device = ""
        self.max_context = 4096
        self.lock = threading.Lock()
        self.active: Generation | None = None
        self.requests = 0
        self.last_speed = 0.0

    def load(self, path: Path, model_id: str, device: str, max_context: int) -> None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoTokenizer

        if device == "auto":
            device = (
                "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
            )
        if device == "cuda" and not torch.cuda.is_available():
            raise ValueError("CUDA 不可用，请检查 NVIDIA 驱动和 PyTorch 安装，或选择 CPU")
        if device == "mps" and not torch.backends.mps.is_available():
            raise ValueError("此设备的 PyTorch MPS 后端不可用，请选择 CPU")
        # CPU / MPS 使用 FP32，避免混合注意力算子在低精度下的兼容性差异。
        dtype = (
            torch.bfloat16
            if device == "cuda" and torch.cuda.is_bf16_supported()
            else (torch.float16 if device == "cuda" else torch.float32)
        )
        tokenizer = AutoTokenizer.from_pretrained(str(path), local_files_only=True, trust_remote_code=False)
        previous_async_load = os.environ.get("HF_DEACTIVATE_ASYNC_LOAD")
        if device == "mps":
            # Metal 的权重转换在并发加载时可能崩溃，MPS 使用官方的串行加载开关。
            os.environ["HF_DEACTIVATE_ASYNC_LOAD"] = "1"
        try:
            model = AutoModelForImageTextToText.from_pretrained(
                str(path),
                local_files_only=True,
                trust_remote_code=False,
                use_safetensors=True,
                dtype=dtype,
                device_map={"": device},
                attn_implementation="sdpa",
            ).eval()
        finally:
            if device == "mps":
                if previous_async_load is None:
                    os.environ.pop("HF_DEACTIVATE_ASYNC_LOAD", None)
                else:
                    os.environ["HF_DEACTIVATE_ASYNC_LOAD"] = previous_async_load
        self.model, self.tokenizer = model, tokenizer
        self.model_id, self.device, self.max_context = model_id, device, max_context

    def cancel(self) -> None:
        if self.active:
            self.active.cancel.set()

    def unload(self) -> None:
        self.cancel()
        with self.lock:
            self.model = self.tokenizer = None
            self.model_id = self.device = ""
            gc.collect()
            if inference_installed():
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                if torch.backends.mps.is_available():
                    torch.mps.empty_cache()

    async def begin(
        self,
        messages: list[dict] | str,
        max_tokens: int,
        temperature: float = 0,
        top_p: float = 1,
        stop: list[str] | None = None,
    ) -> Generation:
        if self.model is None:
            raise HTTPException(503, "请先启动一个已下载的模型")
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, "模型正在处理另一条请求，请稍后重试")
        session = Generation()
        self.active = session
        try:

            def tokenize():
                if isinstance(messages, str):
                    return self.tokenizer(messages, return_tensors="pt")
                return self.tokenizer.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    enable_thinking=False,
                    return_tensors="pt",
                    return_dict=True,
                )

            inputs = await asyncio.to_thread(tokenize)
            session.input_tokens = inputs["input_ids"].shape[-1]
            if session.input_tokens + max_tokens > self.max_context:
                raise HTTPException(
                    400, f"输入与输出预算超过 {self.max_context} token 上下文，请缩短文本或调整设置"
                )
            loop = asyncio.get_running_loop()
            thread = threading.Thread(
                target=self._generate,
                args=(session, loop, inputs, max_tokens, temperature, top_p, stop or []),
                daemon=True,
            )
            thread.start()
            return session
        except BaseException:
            self.active = None
            self.lock.release()
            raise

    def _generate(self, session, loop, inputs, max_tokens, temperature, top_p, stops):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList, TextStreamer

        def emit(event):
            if not loop.is_closed():
                loop.call_soon_threadsafe(session.queue.put_nowait, event)

        filter_ = StopFilter(stops)

        class Streamer(TextStreamer):
            def on_finalized_text(self, text: str, stream_end: bool = False):
                delta = filter_.feed(text, final=stream_end)
                if delta:
                    emit({"type": "delta", "text": delta})

        class CancelCriteria(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return session.cancel.is_set() or filter_.stopped

        started = time.monotonic()
        try:
            options = {
                "max_new_tokens": max_tokens,
                "do_sample": temperature > 0,
                "streamer": Streamer(self.tokenizer, skip_prompt=True, skip_special_tokens=True),
                "stopping_criteria": StoppingCriteriaList([CancelCriteria()]),
            }
            if temperature > 0:
                options.update(temperature=temperature, top_p=top_p)
            with torch.inference_mode():
                output = self.model.generate(**inputs.to(self.device), **options)
            output_tokens = output.shape[-1] - session.input_tokens
            elapsed = time.monotonic() - started
            self.requests += 1
            self.last_speed = output_tokens / max(elapsed, 0.001)
            emit(
                {
                    "type": "done",
                    "input_tokens": session.input_tokens,
                    "output_tokens": output_tokens,
                    "finish_reason": "length"
                    if output_tokens >= max_tokens and not filter_.stopped
                    else "stop",
                    "stop_sequence": filter_.stop_sequence,
                    "elapsed": elapsed,
                    "cancelled": session.cancel.is_set(),
                }
            )
        except Exception as error:
            emit({"type": "error", "message": str(error)})
        finally:
            self.active = None
            self.lock.release()
