"""核心工具测试：文本归一化 / 沙箱路径 / 图片嗅探。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.errors import SandboxViolation
from app.core.files import safe_join, sha256_bytes, sniff_image
from app.core.text import estimate_tokens, normalize_text, strip_front_matter, truncate


def test_normalize_fullwidth_and_case() -> None:
    assert normalize_text("ＡＢＣ　１２３") == "abc 123"
    assert normalize_text("  多   空格\n换行 ") == "多 空格 换行"


def test_truncate() -> None:
    assert truncate("你好世界", 10) == "你好世界"
    assert truncate("你好世界", 3) == "你好…"


def test_estimate_tokens() -> None:
    assert estimate_tokens("你好") >= 1
    assert estimate_tokens("hello world") >= 2
    assert estimate_tokens("") == 0


def test_strip_front_matter() -> None:
    meta, body = strip_front_matter("---\ntitle: x\nscenario: seeding_post\n---\n正文")
    assert meta["title"] == "x"
    assert body == "正文"
    meta2, body2 = strip_front_matter("无 front matter")
    assert meta2 == {} and body2 == "无 front matter"


def test_safe_join_allows_inside(tmp_path: Path) -> None:
    target = safe_join(tmp_path, "a", "b.txt")
    assert str(target).startswith(str(tmp_path.resolve()))


@pytest.mark.parametrize(
    "evil",
    ["../outside.txt", "..\\..\\windows\\system32\\cmd.exe", "C:\\Windows\\notepad.exe", "/etc/passwd"],
)
def test_safe_join_blocks_escape(tmp_path: Path, evil: str) -> None:
    with pytest.raises(SandboxViolation):
        safe_join(tmp_path, evil)


def test_sniff_image_png() -> None:
    from app.services.demo_seed import make_damaged_product_image

    data = make_damaged_product_image()
    mime, width, height = sniff_image(data)
    assert mime == "image/png"
    assert width > 0 and height > 0


def test_sniff_image_rejects_non_image() -> None:
    with pytest.raises(Exception):
        sniff_image(b"not an image")


def test_sha256_bytes_stable() -> None:
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
    assert sha256_bytes(b"abc") != sha256_bytes(b"abd")
