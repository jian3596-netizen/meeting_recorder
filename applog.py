"""日志：仅在出现 WARNING/ERROR 时，在 exe（或脚本）同目录生成 error.log。

平时不产生空文件（FileHandler 用 delay=True，首次写入时才创建）。
同时安装主线程与子线程的未捕获异常钩子，确保崩溃信息也落盘。
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path


def log_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    return base / "error.log"


def setup() -> None:
    handler = logging.FileHandler(log_path(), encoding="utf-8", delay=True)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(threadName)s %(name)s: %(message)s"
        )
    )
    root = logging.getLogger()
    root.setLevel(logging.WARNING)  # 只记录 WARNING 及以上
    root.addHandler(handler)

    def _excepthook(exc_type, exc_value, exc_tb) -> None:
        logging.getLogger("uncaught").error(
            "主线程未捕获异常", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _excepthook

    def _thread_excepthook(args) -> None:
        name = args.thread.name if args.thread else "?"
        logging.getLogger("thread").error(
            "线程「%s」未捕获异常",
            name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _thread_excepthook
