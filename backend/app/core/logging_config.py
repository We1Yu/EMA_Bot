"""
集中式 logging 設定
在所有進入點（scheduler.py、FastAPI lifespan）呼叫 setup_logging() 一次即可。
"""

import logging
import logging.handlers
from pathlib import Path

LOG_FORMAT  = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_file: Path | None = None, level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return  # 避免重複掛載

    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root.addHandler(fh)
