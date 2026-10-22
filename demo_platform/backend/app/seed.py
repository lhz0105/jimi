"""演示剧本：3 个场景的对话与占位图片（独立于 agent 的示例素材）。"""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc")


def _font(size: int):
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for name in _FONT_CANDIDATES:
        candidate = windir / "Fonts" / name
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def damaged_product() -> bytes:
    img = Image.new("RGB", (640, 480), (246, 244, 250))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 370, 640, 480], fill=(228, 222, 238))
    d.rounded_rectangle([210, 130, 430, 400], radius=26, fill=(124, 58, 237), outline=(91, 33, 182), width=3)
    d.arc([430, 220, 530, 320], start=270, end=90, fill=(124, 58, 237), width=18)
    d.line([(300, 140), (322, 210), (296, 268), (332, 336)], fill=(30, 27, 45), width=5, joint="curve")
    d.line([(360, 150), (348, 220), (382, 300)], fill=(30, 27, 45), width=4, joint="curve")
    d.text((16, 444), "演示占位图 · 破损商品", font=_font(18), fill=(120, 110, 140))
    return _png(img)


def face_photo() -> bytes:
    img = Image.new("RGB", (600, 600), (250, 244, 238))
    d = ImageDraw.Draw(img)
    d.ellipse([170, 120, 430, 470], fill=(244, 222, 202), outline=(214, 186, 166), width=3)
    d.ellipse([232, 242, 262, 268], fill=(58, 52, 48))
    d.ellipse([338, 242, 368, 268], fill=(58, 52, 48))
    d.arc([255, 330, 345, 392], start=20, end=160, fill=(190, 96, 96), width=4)
    d.ellipse([236, 300, 286, 332], fill=(240, 160, 160))
    d.ellipse([314, 300, 364, 332], fill=(240, 160, 160))
    d.text((16, 560), "演示占位图 · 面部照片", font=_font(18), fill=(130, 118, 108))
    return _png(img)


def medical_doc() -> bytes:
    img = Image.new("RGB", (800, 1000), (253, 253, 251))
    d = ImageDraw.Draw(img)
    d.text((260, 40), "门诊病历", font=_font(34), fill=(28, 28, 30))
    d.line([(80, 100), (720, 100)], fill=(120, 120, 120), width=2)
    rows = [
        "姓名：王某某            性别：女    年龄：26",
        "就诊时间：2026-09-28",
        "主诉：面部红斑、瘙痒 3 天，",
        "      自述使用某护肤品后出现。",
        "查体：双颊可见片状红斑，边界清晰。",
        "诊断：接触性皮炎（过敏性皮炎）",
        "处理：停用可疑护肤品；口服抗组胺药；",
        "      外用地奈德乳膏，每日 2 次。",
        "医嘱：两周后复诊，如有加重及时就医。",
    ]
    y = 140
    for row in rows:
        d.text((90, y), row, font=_font(24), fill=(35, 35, 35))
        y += 52
    d.line([(90, y + 10), (710, y + 10)], fill=(150, 150, 150), width=2)
    d.text((90, y + 40), "医师签名：李医生    科室：皮肤科", font=_font(20), fill=(60, 60, 60))
    d.ellipse([560, y + 30, 700, y + 170], outline=(200, 40, 40), width=4)
    d.text((600, y + 88), "医院章", font=_font(20), fill=(200, 40, 40))
    return _png(img)


def seeding_image() -> bytes:
    img = Image.new("RGB", (720, 720), (250, 247, 242))
    d = ImageDraw.Draw(img)
    for y in range(720):
        shade = 236 + int(14 * (y / 720))
        d.line([(0, y), (720, y)], fill=(shade, shade - 4, shade - 10))
    d.rounded_rectangle([230, 210, 500, 560], radius=30, fill=(238, 206, 126), outline=(206, 174, 96), width=3)
    d.rectangle([306, 172, 424, 218], fill=(120, 100, 80))
    d.text((112, 64), "终于找到本命面霜！", font=_font(30), fill=(74, 64, 54))
    d.text((150, 636), "演示占位图 · 种草帖配图", font=_font(20), fill=(126, 116, 106))
    return _png(img)


# scenario -> {customer_name, channel, messages: [(role, text, image_factory|None)]}
SCENARIOS: dict[str, dict] = {
    "product_damage": {
        "customer_name": "李女士",
        "channel": "demo",
        "messages": [
            ("customer", "你好，我上周买的这套护肤套装，今天拆开发现里面那瓶精华是碎的。", None),
            ("agent", "非常抱歉给您带来不好的体验，方便发一下商品和包装的照片吗？", None),
            ("customer", "照片发你了，碎得很严重，玻璃碴都在盒子里。", damaged_product),
            ("customer", "我要求整单退款，这个质量真的没法接受。", None),
        ],
    },
    "medical_claim": {
        "customer_name": "王女士",
        "channel": "demo",
        "messages": [
            ("customer", "用了你们的面霜之后我脸就变成这样了，全是红疹。", face_photo),
            ("customer", "医院诊断说我这是激素依赖性皮炎，你们产品肯定激素超标，必须赔偿。", None),
            ("agent", "非常抱歉，方便提供一下医院的诊断证明吗？我们会认真核实。", None),
            ("customer", "诊断单在这里，医生都说很严重，你们必须负责到底。", medical_doc),
        ],
    },
    "seeding_post": {
        "customer_name": "种草内容",
        "channel": "seed_post",
        "messages": [
            (
                "customer",
                "姐妹们！这款面霜真的绝了，我已经回购第 5 瓶了，熬夜脸救星！"
                "质地超级好吸收，一抹就水润，第二天起来皮肤透亮到发光，闭眼入不踩雷，链接我放评论区啦～",
                seeding_image,
            ),
            (
                "customer",
                "评论区：1楼 求链接+1；2楼 已下单，谢谢姐妹分享；"
                "3楼 用了一周，感觉一般般，没那么神；4楼 太贵了吧，学生党劝退",
                None,
            ),
        ],
    },
}

SCENARIO_NAMES = tuple(SCENARIOS.keys())


def get_scenario(name: str) -> dict:
    if name not in SCENARIOS:
        raise KeyError(name)
    return SCENARIOS[name]
