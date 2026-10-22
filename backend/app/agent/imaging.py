"""图片本地取证（EXIF/指纹）与带缓存的视觉分析（节点与工具共用）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from app.db.repositories import image_hashes as image_hashes_repo
from app.db.repositories import vision_cache as vision_cache_repo
from app.llm.vision import analyze_image, prompt_hash
from app.observability.events import EventType

logger = logging.getLogger(__name__)

# AI 生成工具常写入的软件标记
_AI_SOFTWARE_MARKERS = (
    "midjourney",
    "stable diffusion",
    "dall-e",
    "dalle",
    "firefly",
    "grok",
    "flux",
    "comfyui",
    "aigc",
    "generated",
)

_EXIF_TAG_NAMES = {v: k for k, v in ExifTags.TAGS.items()}


def exif_summary(path: Path) -> dict[str, Any]:
    """提取 EXIF 关键信息；无 EXIF 也如实记录（AI 图/转发图常被清洗）。"""
    summary: dict[str, Any] = {"has_exif": False, "fields": {}}
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return summary
            summary["has_exif"] = True
            interesting = {
                "Make": "相机厂商",
                "Model": "相机型号",
                "Software": "软件",
                "DateTime": "拍摄时间",
                "DateTimeOriginal": "原始拍摄时间",
                "GPSInfo": "GPS信息",
                "ImageDescription": "图像描述",
                "Artist": "作者",
            }
            for tag, label in interesting.items():
                tag_id = _EXIF_TAG_NAMES.get(tag)
                if tag_id is None:
                    continue
                value = None
                try:
                    value = exif.get(tag_id)
                except Exception:  # pragma: no cover
                    value = None
                if value is not None:
                    text = str(value)
                    summary["fields"][label] = text[:200]
    except Exception as exc:  # pragma: no cover
        summary["error"] = str(exc)
    return summary


def detect_ai_software_marker(exif_info: dict[str, Any]) -> str | None:
    software = str((exif_info.get("fields") or {}).get("软件", "")).lower()
    for marker in _AI_SOFTWARE_MARKERS:
        if marker in software:
            return software
    return None


def compute_hashes(path: Path) -> dict[str, str | None]:
    import imagehash

    try:
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            return {
                "phash": str(imagehash.phash(rgb)),
                "dhash": str(imagehash.dhash(rgb)),
                "ahash": str(imagehash.average_hash(rgb)),
            }
    except Exception as exc:  # pragma: no cover
        logger.warning("hash computation failed: %s", exc)
        return {"phash": None, "dhash": None, "ahash": None}


def hamming(hex_a: str, hex_b: str) -> int:
    import imagehash

    return int(imagehash.hex_to_hash(hex_a) - imagehash.hex_to_hash(hex_b))


async def record_image_forensics(
    runtime: Any, image: dict[str, Any]
) -> dict[str, Any]:
    """计算并落库图片指纹 + EXIF，返回检测结果（供 local_forensics 节点使用）。"""
    path = Path(image["path"])
    exif_info = exif_summary(path)
    hashes = compute_hashes(path)
    await image_hashes_repo.upsert(
        runtime.db,
        sha256=image["sha256"],
        phash=hashes["phash"],
        dhash=hashes["dhash"],
        ahash=hashes["ahash"],
        width=image.get("width"),
        height=image.get("height"),
        mime=image.get("mime"),
        exif=exif_info,
        first_run_id=runtime.run_id,
    )
    return {
        "sha256": image["sha256"],
        "exif": exif_info,
        "hashes": hashes,
        "ai_software_marker": detect_ai_software_marker(exif_info),
    }


async def find_similar_images(
    runtime: Any, sha256: str, max_distance: int | None = None
) -> list[dict[str, Any]]:
    """在历史图库中查找相似图片（pHash Hamming 距离）。"""
    image = runtime.image_by_sha(sha256)
    if image is None:
        return []
    sha256 = image["sha256"]
    threshold = max_distance if max_distance is not None else runtime.settings.phash_hamming_threshold
    current = await image_hashes_repo.get(runtime.db, sha256)
    if current is None or not current.get("phash"):
        return []
    current_phash = current["phash"]
    candidates = await image_hashes_repo.list_with_phash(runtime.db, exclude_sha=sha256)
    matches: list[dict[str, Any]] = []
    for row in candidates:
        try:
            distance = hamming(current_phash, row["phash"])
        except Exception:  # pragma: no cover
            continue
        if distance <= threshold:
            matches.append(
                {
                    "sha256": row["sha256"],
                    "distance": distance,
                    "first_run_id": row.get("first_run_id"),
                    "created_at": row.get("created_at"),
                }
            )
    matches.sort(key=lambda m: m["distance"])
    return matches


async def analyze_image_cached(
    runtime: Any,
    *,
    sha256: str,
    prompt_text: str,
    system: str | None = None,
    focus: str = "",
    emit: bool = True,
) -> dict[str, Any]:
    """带持久缓存的视觉分析（同图同提示词只调用一次，可跨运行复用）。"""
    image = runtime.image_by_sha(sha256)
    if image is None:
        available = "、".join(img["sha256"][:12] for img in runtime.images) or "无"
        return {
            "status": "error",
            "message": f"图片不存在于本案: {sha256}；可用图片前缀: {available}",
        }
    # 模型可能只拿到清单里的短前缀，统一归一为完整 sha 后再做缓存/落库
    sha256 = image["sha256"]

    # 缓存键包含运行模式：fake 与 real 的识图结果绝不互相命中（切换模式后自动分离）
    model = f"{runtime.settings.llm_mode}:{runtime.settings.llm_vision_model}"
    phash_key = prompt_hash(prompt_text, focus)
    cached = await vision_cache_repo.get(runtime.db, sha256, phash_key, model)
    if cached is not None:
        if emit:
            # 成对发射，面板中能看到"调用 → 缓存命中"的完整链路
            runtime.emitter.emit(
                EventType.TOOL_CALL,
                {
                    "tool": "vision_analyze",
                    "args_preview": f"sha256={sha256[:12]}…（缓存查询）",
                    "cache_lookup": True,
                },
            )
            runtime.emitter.emit(
                EventType.TOOL_RESULT,
                {
                    "tool": "vision_analyze",
                    "status": "ok",
                    "latency_ms": 0,
                    "result_preview": "（缓存命中，未产生新调用）",
                    "cache_hit": True,
                },
            )
        return {"status": "ok", "cache_hit": True, "data": cached}

    if runtime.llm_vision is None:
        return {"status": "error", "message": "识图模型未配置"}

    result = await analyze_image(
        runtime.llm_vision,
        image_path=Path(image["path"]),
        prompt=prompt_text + (f"\n\n【本次特别关注】{focus}" if focus else ""),
        system=system,
    )
    payload = result.get("data")
    if payload is None:
        # 解析失败不写缓存：下次可换预算/提示词重试，避免坏结果永久命中
        payload = {"parse_error": True, "raw": result.get("raw", "")[:800]}
    else:
        await vision_cache_repo.put(runtime.db, sha256, phash_key, model, payload)
    return {"status": "ok", "cache_hit": False, "data": payload, "raw": result.get("raw", "")}
