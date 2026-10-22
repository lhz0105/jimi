"""启动入口：python scripts/run_server.py [--host H] [--port P] [--reload]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="run jimi-evidence backend")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="dev auto-reload")
    args = parser.parse_args()

    # 注意：EventBus 为进程内 pub/sub，必须单 worker
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
