"""报告 Markdown 渲染回归：表格行必须连续（GFM 遇空行即终止），details 标签保留。"""

from __future__ import annotations

from app.agent.report_builder import render_markdown


def _report() -> dict:
    return {
        "report_id": "rep_test",
        "run_id": "run_test",
        "generated_at": 1730000000000,
        "scenario": "product_damage_claim",
        "summary": {
            "conclusion": "suspicious",
            "risk_level": "high",
            "confidence": 0.72,
            "one_line": "综合证据指向疑似欺诈",
        },
        "evidence_chain": [
            {
                "evidence_id": "ev_0001",
                "category": "metadata",
                "source": {"type": "image", "ref": "sha256:abc", "detail": "EXIF 元数据"},
                "tool": "exif_check",
                "finding": "图片无 EXIF 元数据（提示：社交平台转发/截图/编辑均会清除 EXIF）",
                "direction": "unknown",
                "weight": 0.2,
            },
            {
                "evidence_id": "ev_0002",
                "category": "aigc_artifact",
                "source": {"type": "image", "ref": "sha256:abc", "detail": "产品主体"},
                "tool": "vision_analyze",
                "finding": "产品主体区域疑似 AIGC 生成（含 | 管道符需转义）",
                "direction": "supports_fake",
                "weight": 0.85,
            },
        ],
        "thought_timeline": [
            {"seq": 12, "ts": 1730000000000, "node": "investigate", "summary": "检索知识库命中 3 条"},
        ],
        "recommended_actions": [
            {"action": "manual_review", "priority": 1, "note": "转人工复核"},
            {"action": "request_original_media", "priority": 2, "note": "要求原始文件"},
        ],
        "input_digest": {
            "conversation_id": None,
            "message_count": 4,
            "image_sha256s": ["abc123"],
            "rules_version": "2026-10-11.1",
        },
        "cost": {
            "llm_calls": 3,
            "prompt_tokens": 2100,
            "completion_tokens": 220,
            "tool_calls": 2,
            "vision_calls": 1,
            "tavily_calls": 0,
            "est_cost": 0.0025,
        },
        "versions": {
            "rules": "2026-10-11.1",
            "kb": "kb_x",
            "prompts": "p1",
            "models": {"main": "deepseek-v4-flash", "vision": "qwen3.7-flash"},
        },
        "limitations": ["EXIF 可被清洗", "视觉模型输出存在不确定性"],
    }


def test_evidence_table_rows_are_contiguous() -> None:
    """GFM 表格：表头、分隔线、数据行必须紧邻，行间不能有空行。"""
    lines = render_markdown(_report()).splitlines()
    header = lines.index("| # | 编号 | 类别 | 方向 | 权重 | 发现 |")
    assert lines[header + 1].startswith("|---")
    assert lines[header + 2].startswith("| 1 | ev_0001 |")
    assert lines[header + 3].startswith("| 2 | ev_0002 |")
    assert lines[header + 4] == ""  # 表格结束后才允许空行


def test_pipe_in_finding_is_escaped() -> None:
    md = render_markdown(_report())
    assert "含 \\| 管道符需转义" in md


def test_details_tag_preserved() -> None:
    md = render_markdown(_report())
    assert "<details>" in md
    assert "</details>" in md
    assert "- [seq 12] investigate：检索知识库命中 3 条" in md


def test_lists_are_tight() -> None:
    """推荐动作与限制列表不应出现条目间空行（trim_blocks）。"""
    lines = render_markdown(_report()).splitlines()
    action_idx = lines.index("1. **manual_review**（优先级 1） — 转人工复核")
    assert lines[action_idx + 1].startswith("2. **request_original_media**")
