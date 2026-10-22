"""知识库导入 CLI。

用法:
  python scripts/ingest_kb.py            # 增量导入
  python scripts/ingest_kb.py --rebuild  # 全量重建（清空向量集合）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows 控制台默认 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from app.config import get_settings
from app.db.database import Database
from app.db.migrate import migrate
from app.rag.embedder import Embedder
from app.rag.ingest import ensure_kb_seed, ingest_all
from app.rag.retriever import HybridRetriever
from app.rag.store import VectorStore


async def run(rebuild: bool) -> int:
    settings = get_settings()
    settings.ensure_dirs()

    db = Database(settings.db_path)
    await db.connect()
    try:
        await migrate(db)

        copied = ensure_kb_seed(settings)
        if copied:
            print(f"示例知识库已复制 {copied} 个文件 -> {settings.kb_dir}")

        embedder = Embedder(settings)
        store = VectorStore(settings)
        retriever = HybridRetriever(settings, embedder, store)

        stats = await ingest_all(
            settings, db, retriever, embedder, store, rebuild=rebuild
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        if not embedder.available:
            print(f"[warn] 向量模型不可用，当前为 {retriever.rag_mode}: {embedder.error}")
        return 0
    finally:
        # 必须关闭，否则 aiosqlite 工作线程会阻塞解释器退出
        await db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="ingest knowledge base")
    parser.add_argument("--rebuild", action="store_true", help="清空向量集合并全量重建")
    args = parser.parse_args()
    return asyncio.run(run(args.rebuild))


if __name__ == "__main__":
    raise SystemExit(main())
