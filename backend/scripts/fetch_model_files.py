"""手动下载向量模型文件（网络受限/代理不稳时的可靠路径）。

默认走 hf-mirror.com，优先用系统 curl（支持断点续传，国内直连通常 1MB/s 左右）。
下载目录：EMBEDDING_CACHE_DIR/<模型简称>/，Embedder 会自动识别该目录（离线可用）。

用法:
  python scripts/fetch_model_files.py                # 自动（有 curl 用 curl）
  python scripts/fetch_model_files.py --force        # 重新下载已存在文件
  python scripts/fetch_model_files.py --endpoint https://hf-mirror.com
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows 控制台默认 GBK，强制 UTF-8 输出避免中文/符号编码崩溃
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from app.config import get_settings

REPO = "Qdrant/bge-small-zh-v1.5"
FILES = [
    "config.json",
    "ort_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "model_optimized.onnx",
]


def _curl_download(url: str, target: Path, *, use_proxy: bool) -> bool:
    cmd = ["curl", "-L", "--fail", "--retry", "3", "--retry-delay", "2", "-C", "-", "-o", str(target)]
    if not use_proxy:
        cmd += ["--noproxy", "*"]
    cmd.append(url)
    print(f"    - curl {'(直连)' if not use_proxy else '(走代理)'} {url.rsplit('/', 1)[-1]}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"      curl 失败: {result.stderr.strip()[:200]}")
        return False
    return True


def _httpx_download(url: str, target: Path) -> bool:
    import httpx

    print(f"    - httpx {url.rsplit('/', 1)[-1]}")
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as response:
        response.raise_for_status()
        tmp = target.with_suffix(target.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in response.iter_bytes(1 << 20):
                f.write(chunk)
        tmp.replace(target)
    return True


def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="fetch embedding model files")
    parser.add_argument("--endpoint", default=settings.hf_endpoint or "https://huggingface.co")
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    short_name = settings.embedding_model.split("/")[-1]
    dest = settings.embedding_cache_dir / short_name
    dest.mkdir(parents=True, exist_ok=True)
    base = args.endpoint.rstrip("/")
    has_proxy = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    has_curl = shutil.which("curl") is not None

    print(f"模型: {settings.embedding_model} -> {dest}")
    print(f"端点: {base} | curl: {'有' if has_curl else '无'} | 代理环境变量: {'有' if has_proxy else '无'}")

    failed: list[str] = []
    for name in FILES:
        target = dest / name
        if target.exists() and target.stat().st_size > 0 and not args.force:
            print(f"    ✓ 已存在 {name} ({target.stat().st_size // 1024} KB)")
            continue
        url = f"{base}/{args.repo}/resolve/main/{name}"
        started = time.time()
        ok = False
        if has_curl:
            # 直连优先（hf-mirror 对国内直连更快）；失败再回退走代理
            ok = _curl_download(url, target, use_proxy=False)
            if not ok and has_proxy:
                ok = _curl_download(url, target, use_proxy=True)
        if not ok:
            try:
                ok = _httpx_download(url, target)
            except Exception as exc:
                print(f"      httpx 失败: {exc}")
        if ok and target.exists() and target.stat().st_size > 0:
            size_mb = target.stat().st_size / 1024 / 1024
            print(f"      ✓ {name} {size_mb:.1f} MB / {time.time() - started:.0f}s")
        else:
            failed.append(name)

    if failed:
        print(f"\n[FAIL] 以下文件未下载成功: {failed}")
        print("       可重跑本脚本（curl 支持断点续传），或手动放置到上述目录。")
        return 1

    print("\n[OK] 模型文件就绪。Embedder 将自动使用该目录（无需再联网）。")
    print(f"     目录: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
