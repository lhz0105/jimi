"""中文分块测试。"""

from __future__ import annotations

from app.rag.chunker import chunk_document


def test_front_matter_extracted() -> None:
    raw = """---
title: 测试文档
scenario: seeding_post
---
# 标题
这是正文内容，需要足够长度才能形成有效分块。测试内容测试内容测试内容测试内容。
第二句继续补充，确保聚合后的段落超过最小长度阈值，从而被保留下来。
"""
    meta, chunks = chunk_document(raw)
    assert meta["title"] == "测试文档"
    assert meta["scenario"] == "seeding_post"
    assert chunks


def test_heading_path_preserved() -> None:
    raw = """# 一级
## 二级标题
这是二级标题下的内容，需要足够长度才能成为有效分块。测试内容测试内容测试内容测试内容。
### 三级标题
三级标题下的内容，同样需要足够长度。测试内容测试内容测试内容测试内容测试内容。
"""
    _, chunks = chunk_document(raw)
    paths = {c["heading_path"] for c in chunks}
    assert any("一级 > 二级标题" in p for p in paths)
    assert any("一级 > 二级标题 > 三级标题" in p for p in paths)


def test_long_text_is_split_with_overlap() -> None:
    sentence = "这是一个用于测试的句子，包含足够多的字符以验证分块逻辑是否正确工作。"
    raw = "# 长文\n" + sentence * 40
    _, chunks = chunk_document(raw, chunk_size=300, overlap=50)
    assert len(chunks) > 5
    assert all(len(c["text"]) <= 300 + 80 for c in chunks)  # 允许 overlap 带来的溢出余量
    assert [c["ordinal"] for c in chunks] == list(range(1, len(chunks) + 1))


def test_tiny_fragments_filtered() -> None:
    raw = "# 标题\n短。"
    _, chunks = chunk_document(raw)
    assert chunks == []  # 低于最小长度阈值


def test_works_without_headings() -> None:
    raw = "没有标题的一段文字。" * 20
    _, chunks = chunk_document(raw)
    assert chunks and chunks[0]["heading_path"] == ""
