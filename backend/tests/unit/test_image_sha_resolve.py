"""图片 sha 定位：模型可能只拿到清单里的短前缀 / 带省略号的标识。"""

from __future__ import annotations

from app.agent.runtime import RunRuntime

FULL = "3c19d88c5b70" + "0" * 52


class _Stub:
    case = {"images": [{"sha256": FULL, "path": "x.png"}]}
    images = RunRuntime.images
    image_by_sha = RunRuntime.image_by_sha


def test_image_by_sha_accepts_full_and_prefix_forms() -> None:
    stub = _Stub()
    assert stub.image_by_sha(FULL)["sha256"] == FULL
    assert stub.image_by_sha("3c19d88c5b70")["sha256"] == FULL
    assert stub.image_by_sha("3c19d88c5b70…")["sha256"] == FULL
    assert stub.image_by_sha("sha256:3c19d88c5b70…")["sha256"] == FULL
    assert stub.image_by_sha("  3C19D88C5B70  ")["sha256"] == FULL


def test_image_by_sha_rejects_unknown_or_too_short() -> None:
    stub = _Stub()
    assert stub.image_by_sha("") is None
    assert stub.image_by_sha("3c19") is None
    assert stub.image_by_sha("ffffffffffff") is None
