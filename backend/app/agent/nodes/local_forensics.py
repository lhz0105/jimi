"""local_forensics：全部图片的 EXIF 检查 + 感知哈希历史图库比对。无 LLM 调用（零成本）。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.agent.evidence import EvidenceBuilder
from app.agent.imaging import find_similar_images, record_image_forensics
from app.observability.decorators import observed_node

logger = logging.getLogger(__name__)


def _describe_exif(exif: dict[str, Any]) -> str:
    fields = exif.get("fields") or {}
    parts = [f"{k}={v}" for k, v in list(fields.items())[:3]]
    return "，".join(parts) if parts else "无关键字段"


@observed_node("local_forensics")
async def local_forensics(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    builder = EvidenceBuilder(state)
    evidence: list[dict[str, Any]] = []
    findings: dict[str, Any] = {}
    warnings: list[str] = []

    for image in runtime.images:
        sha = image["sha256"]
        path = Path(image["path"])
        if not path.exists():
            warnings.append(f"图片文件缺失: {sha[:12]}")
            continue

        info = await record_image_forensics(runtime, image)
        if runtime.settings.image_duplicate_check_enabled:
            try:
                similar = await find_similar_images(runtime, sha)
            except Exception as exc:  # pragma: no cover
                logger.warning("similar image search failed: %s", exc)
                similar = []
        else:
            similar = []
        findings[sha] = {"forensics": info, "similar_images": similar}

        marker = info.get("ai_software_marker")
        exif = info.get("exif") or {}
        if marker:
            evidence.append(
                builder.add(
                    category="metadata",
                    source={"type": "image", "ref": f"sha256:{sha[:12]}", "detail": "EXIF Software 字段"},
                    tool="exif_check",
                    finding=f"EXIF 软件字段包含生成工具标记「{marker}」，强烈提示图片由 AI 工具生成/处理",
                    direction="supports_fake",
                    weight=0.9,
                )
            )
        elif exif.get("has_exif"):
            evidence.append(
                builder.add(
                    category="metadata",
                    source={"type": "image", "ref": f"sha256:{sha[:12]}", "detail": "EXIF 元数据"},
                    tool="exif_check",
                    finding=f"图片保留拍摄元数据（{_describe_exif(exif)}），符合真实拍摄设备的痕迹",
                    direction="supports_genuine",
                    weight=0.3,
                )
            )
        else:
            evidence.append(
                builder.add(
                    category="metadata",
                    source={"type": "image", "ref": f"sha256:{sha[:12]}", "detail": "EXIF 元数据"},
                    tool="exif_check",
                    finding="图片无 EXIF 元数据（提示：社交平台转发/截图/编辑均会清除 EXIF，此项不能单独作为判定依据）",
                    direction="unknown",
                    weight=0.2,
                )
            )

        if similar:
            best = similar[0]
            evidence.append(
                builder.add(
                    category="duplicate_image",
                    source={"type": "image", "ref": f"sha256:{sha[:12]}", "detail": "感知哈希比对"},
                    tool="phash_check",
                    finding=(
                        f"该图与历史索赔图库中 {len(similar)} 张图片视觉高度相似"
                        f"（最小 Hamming 距离 {best['distance']}，首次出现于 run {best.get('first_run_id') or '未知'}），"
                        "提示图片被跨案复用"
                    ),
                    direction="supports_fake",
                    weight=0.8,
                    raw_ref={"similar": similar[:5]},
                )
            )
        elif runtime.settings.image_duplicate_check_enabled:
            findings[sha]["forensics"]["duplicate_checked"] = True

    return {"evidence": evidence, "image_findings": findings, "warnings": warnings}
