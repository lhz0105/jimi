"""内置演示剧本：3 个场景的会话消息 + 占位图片生成。

占位图片用 PIL 现场绘制（含可读文字），便于在无真实素材时演示完整链路；
真实素材到位后可直接用演示平台上传接口替换。
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc")


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for name in _FONT_CANDIDATES:
        candidate = windir / "Fonts" / name
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
    return ImageFont.load_default()


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_damaged_product_image() -> bytes:
    """产品破损索赔占位图：杯子 + 裂纹。"""
    img = Image.new("RGB", (640, 480), (238, 238, 240))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 360, 640, 480], fill=(210, 205, 200))
    d.rounded_rectangle([200, 120, 440, 400], radius=24, fill=(70, 110, 180), outline=(40, 70, 130), width=3)
    d.arc([440, 220, 540, 320], start=270, end=90, fill=(70, 110, 180), width=18)
    for poly in (
        [(300, 130), (320, 200), (295, 260), (330, 330)],
        [(360, 140), (350, 210), (380, 290)],
    ):
        d.line(poly, fill=(25, 25, 30), width=5, joint="curve")
    d.line([(240, 350), (300, 385), (380, 360)], fill=(25, 25, 30), width=4, joint="curve")
    font = _load_font(20)
    d.text((16, 440), "演示占位图 · 破损商品", font=font, fill=(90, 90, 90))
    return _png_bytes(img)


def make_medical_doc_image() -> bytes:
    """诊断单占位图：门诊病历（诊断=接触性皮炎/过敏性皮炎）。"""
    img = Image.new("RGB", (800, 1000), (252, 252, 250))
    d = ImageDraw.Draw(img)
    font_title = _load_font(34)
    font = _load_font(24)
    font_small = _load_font(20)
    d.text((250, 40), "门诊病历", font=font_title, fill=(30, 30, 30))
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
        d.text((90, y), row, font=font, fill=(35, 35, 35))
        y += 52
    d.line([(90, y + 10), (710, y + 10)], fill=(150, 150, 150), width=2)
    d.text((90, y + 40), "医师签名：李医生    科室：皮肤科", font=font_small, fill=(60, 60, 60))
    d.ellipse([560, y + 30, 700, y + 170], outline=(200, 40, 40), width=4)
    d.text((590, y + 80), "医院章", font=font_small, fill=(200, 40, 40))
    return _png_bytes(img)


def make_face_photo_image() -> bytes:
    """面部照片占位图（用于烂脸/美颜场景）。"""
    img = Image.new("RGB", (600, 600), (235, 220, 205))
    d = ImageDraw.Draw(img)
    d.ellipse([170, 120, 430, 470], fill=(240, 214, 190), outline=(200, 170, 150), width=3)
    d.ellipse([230, 240, 260, 265], fill=(60, 55, 52))
    d.ellipse([340, 240, 370, 265], fill=(60, 55, 52))
    d.arc([255, 330, 345, 390], start=20, end=160, fill=(170, 90, 90), width=4)
    d.ellipse([235, 300, 285, 330], fill=(235, 150, 150))
    d.ellipse([315, 300, 365, 330], fill=(235, 150, 150))
    font = _load_font(20)
    d.text((16, 560), "演示占位图 · 面部照片", font=font, fill=(90, 90, 90))
    return _png_bytes(img)


def make_seeding_post_image() -> bytes:
    """种草帖配图占位图。"""
    img = Image.new("RGB", (720, 720), (250, 246, 240))
    d = ImageDraw.Draw(img)
    for y in range(720):
        shade = 230 + int(20 * (y / 720))
        d.line([(0, y), (720, y)], fill=(shade, shade - 6, shade - 14))
    d.rounded_rectangle([220, 200, 500, 560], radius=30, fill=(240, 200, 120), outline=(200, 160, 90), width=3)
    d.rectangle([300, 160, 420, 210], fill=(120, 100, 80))
    font = _load_font(30)
    d.text((110, 60), "终于找到本命面霜！", font=font, fill=(70, 60, 50))
    font_small = _load_font(22)
    d.text((150, 630), "演示占位图 · 种草帖配图", font=font_small, fill=(120, 110, 100))
    return _png_bytes(img)


# (role, text, image_factory|None)
_SCENARIOS: dict[str, dict] = {
    "product_damage_claim": {
        "customer_name": "演示客户·破损索赔",
        "channel": "demo",
        "messages": [
            ("customer", "你们这什么质量啊，刚收到的杯子就碎成这样！", make_damaged_product_image),
            ("customer", "我要求全额退款，两百多的东西一次就碎，太气人了", None),
            ("agent", "非常抱歉给您带来困扰，麻烦提供订单号，我们马上核实处理", None),
            ("customer", "订单号 202610060088，照片已经发了，赶紧给我退款", None),
        ],
    },
    "medical_cert_claim": {
        "customer_name": "演示客户·烂脸索赔",
        "channel": "demo",
        "messages": [
            ("customer", "用了你们那个面霜之后我脸就变成这样了，全是红疹", make_face_photo_image),
            ("customer", "医院诊断说我这是激素依赖性皮炎，你们产品肯定激素超标，必须赔偿", None),
            ("agent", "非常抱歉，方便提供医院的诊断证明吗？我们会认真核实", None),
            ("customer", "诊断单在这里，医生都说很严重，你们必须负责到底", make_medical_doc_image),
        ],
    },
    "seeding_post": {
        "customer_name": "演示内容·种草帖",
        "channel": "seed_post",
        "messages": [
            (
                "customer",
                "姐妹们！这款面霜真的绝了，我已经回购第5瓶了，熬夜脸救星！"
                "质地超级好吸收，一抹就水润，第二天起来皮肤透亮到发光，"
                "闭眼入不踩雷，链接我放评论区啦～",
                make_seeding_post_image,
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

SCENARIO_NAMES = tuple(_SCENARIOS.keys())


def get_scenario(scenario: str) -> dict:
    if scenario not in _SCENARIOS:
        raise KeyError(scenario)
    return _SCENARIOS[scenario]
