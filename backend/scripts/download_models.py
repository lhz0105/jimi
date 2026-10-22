"""预下载本地向量模型（走 HF_ENDPOINT 镜像），并做一次编码冒烟。

用法: python scripts/download_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows 控制台默认 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from app.config import get_settings
from app.rag.embedder import Embedder


def main() -> int:
    settings = get_settings()
    settings.ensure_dirs()
    print(f"[1/2] 加载/下载向量模型: {settings.embedding_model}")
    print(f"      cache: {settings.embedding_cache_dir}")
    print(f"      HF_ENDPOINT: {settings.hf_endpoint or '(官方)'}")

    embedder = Embedder(settings)
    if not embedder.available:
        print(f"[FAIL] 模型不可用: {embedder.error}")
        print("       排障建议：")
        print("       1) 确认 HF_ENDPOINT=https://hf-mirror.com（国内镜像）")
        print("       2) 若本机开了代理，hf-mirror 直连通常更快：")
        print('          bash:  NO_PROXY=hf-mirror.com no_proxy=hf-mirror.com <本命令>')
        print('          PowerShell: $env:NO_PROXY="hf-mirror.com"; <本命令>')
        print("       3) 仍下载失败时，改用 curl 手动下载（更稳、可断点续传）：")
        print("          python scripts/fetch_model_files.py")
        return 1

    print("[2/2] 编码冒烟测试…")
    vector = embedder.embed_query("商品破损索赔图片鉴别")
    print(f"[OK] 向量维度: {len(vector)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
