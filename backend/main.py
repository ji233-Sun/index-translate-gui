import argparse
import asyncio
import os
import sys
import threading
from pathlib import Path

import psutil
import uvicorn

from studio.service import Studio, create_control


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    token = os.environ.get("INDEX_STUDIO_CONTROL_TOKEN")
    if not token:
        raise SystemExit("INDEX_STUDIO_CONTROL_TOKEN is required")
    studio = Studio(args.data_dir)
    server = uvicorn.Server(
        uvicorn.Config(
            create_control(studio, token),
            host="127.0.0.1",
            port=args.port,
            access_log=False,
            log_level="warning",
            timeout_graceful_shutdown=3,
        )
    )
    if os.environ.get("INDEX_STUDIO_WATCH_STDIN") == "1":
        loop = asyncio.get_running_loop()

        def watch_stdin():
            sys.stdin.read()
            try:
                asyncio.run_coroutine_threadsafe(studio.shutdown(), loop).result(timeout=3)
            finally:
                os._exit(0)

        threading.Thread(target=watch_stdin, daemon=True).start()

    async def watch_parent():
        parent = psutil.Process(args.parent_pid) if args.parent_pid else None
        while parent:
            await asyncio.sleep(2)
            if not parent.is_running():
                await studio.shutdown()
                # 硬件推理线程可能停在原生算子，宿主退出后必须回收整个工作进程。
                os._exit(0)

    watcher = asyncio.create_task(watch_parent())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await studio.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
