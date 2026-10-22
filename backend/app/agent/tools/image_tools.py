"""图片指纹工具：历史索赔图库比对（识别同图复用/跨客户重复索赔）。"""

from __future__ import annotations

from typing import Any

from app.agent.imaging import find_similar_images


async def find_similar_claim_images_impl(runtime: Any, sha256: str) -> str:
    if not runtime.settings.image_duplicate_check_enabled:
        return "图片重复排查已停用（IMAGE_DUPLICATE_CHECK_ENABLED=false）"
    matches = await find_similar_images(runtime, sha256)
    if not matches:
        return "图库中未发现相似图片（该图目前仅在当前案件中）"
    lines = [f"发现 {len(matches)} 张相似历史图片："]
    for m in matches[:10]:
        lines.append(
            f"- sha256={m['sha256'][:12]}… 距离={m['distance']} 首次出现run={m.get('first_run_id')}"
        )
    return "\n".join(lines)
