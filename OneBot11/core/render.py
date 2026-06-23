"""
Pillow 图片渲染 — 替代 HTML+Playwright，轻量 ~5MB。
直接画布绘制帮助图片和记录表格，与 Java 原版 Canvas 方式一致。
"""
from io import BytesIO
from typing import Optional, List

from PIL import Image, ImageDraw, ImageFont

from .models import PunishRecord

# ---- 中文字体查找 ----

_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/msyh.ttc",        # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf",       # 黑体
    "C:/Windows/Fonts/simsun.ttc",       # 宋体
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]

_loaded_fonts: dict[tuple[int, bool], ImageFont.FreeTypeFont] = {}


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (size, bold)
    if key in _loaded_fonts:
        return _loaded_fonts[key]

    for path in _FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size)
            _loaded_fonts[key] = font
            return font
        except (OSError, IOError):
            continue

    # 无中文字体，用 Pillow 默认（英文 only，中文变方块）
    font = ImageFont.load_default()
    _loaded_fonts[key] = font
    return font


def _get_text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    """Pillow textlength"""
    try:
        return font.getlength(text)
    except AttributeError:
        # 旧版 Pillow
        return font.getsize(text)[0]


# ---- 帮助图片 ----

def render_help(title: str, subtitle: Optional[str],
                lines: List[str]) -> bytes:
    """渲染帮助图片，返回 PNG 字节"""
    font_title = _get_font(32, bold=True)
    font_sub = _get_font(20, bold=False)
    font_section = _get_font(22, bold=True)
    font_cmd = _get_font(20, bold=True)
    font_desc = _get_font(19, bold=False)
    font_example = _get_font(18, bold=False)
    font_warn = _get_font(19, bold=False)

    left_pad = 28
    right_pad = 20
    width = 820
    content_w = width - left_pad - right_pad

    # 第一遍：计算高度
    y = 48
    if subtitle:
        y += 36
    div_y = y + 12
    y = div_y + 28

    for line in lines:
        if not line:
            y += 18
            continue
        prefix = line[0]
        if prefix == '#':
            y += 42
        elif prefix == '>':
            y += 38
        elif prefix == '-':
            y += 34
        elif prefix == '~':
            y += 30
        elif prefix == '!':
            y += 34
        else:
            y += 34
    height = y + 30

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # 标题
    draw.text((left_pad, 16), title, fill="#1A237E", font=font_title)

    # 副标题
    if subtitle:
        draw.text((left_pad, 50), subtitle, fill="#757575", font=font_sub)

    # 分隔线
    draw.line((left_pad, div_y, width - right_pad, div_y), fill="#E0E0E0", width=2)

    # 内容
    y = div_y + 20
    for line in lines:
        if not line:
            y += 18
            continue
        prefix = line[0]
        text = line[2:] if len(line) > 2 else ""
        indent = 0 if prefix in ('#', '>') else 20

        if prefix == '#':
            draw.text((left_pad + indent, y), text, fill="#1565C0", font=font_section)
            y += 42
        elif prefix == '>':
            draw.text((left_pad + indent, y), text, fill="#1A237E", font=font_cmd)
            y += 38
        elif prefix == '-':
            draw.text((left_pad + indent, y), text, fill="#212121", font=font_desc)
            y += 34
        elif prefix == '~':
            draw.text((left_pad + indent, y), text, fill="#757575", font=font_example)
            y += 30
        elif prefix == '!':
            draw.text((left_pad + indent, y), text, fill="#E65100", font=font_warn)
            y += 34
        else:
            draw.text((left_pad + indent, y), text, fill="#212121", font=font_desc)
            y += 34

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---- 记录表格 ----

_COLORS = {
    "已执行": "#2E7D32",
    "已撤销": "#F57F17",
    "执行失败": "#C62828",
    "部分失败": "#B71C1C",
    "不合规": "#757575",
}

_HEADERS = ["ID", "时间", "发起群", "发起者", "方式", "内容", "原因", "状态", "撤销时间", "撤销原因"]
_COL_WIDTHS = [50, 120, 110, 110, 55, 70, 140, 70, 120, 140]
ROW_H = 42
HEADER_H = 46


def render_record_table(records: List[PunishRecord]) -> bytes:
    """渲染记录表格图片，返回 PNG 字节"""
    from datetime import datetime

    font_title = _get_font(28, bold=True)
    font_header = _get_font(18, bold=True)
    font_cell = _get_font(17, bold=False)
    fmt = "%m-%d %H:%M"

    # 计算列 X 位置
    col_x = []
    x = 16
    for w in _COL_WIDTHS:
        col_x.append(x)
        x += w + 12
    width = x + 16
    header_y = 68
    height = header_y + HEADER_H + len(records) * ROW_H + 30

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # 标题
    draw.text((20, 20), f"处罚记录列表 ({len(records)}条)",
              fill="#1A237E", font=font_title)

    # 表头背景
    draw.rounded_rectangle(
        (12, header_y - 4, width - 12, header_y + HEADER_H - 10),
        radius=10, fill="#3F51B5",
    )

    # 表头文字
    for i, h in enumerate(_HEADERS):
        draw.text((col_x[i], header_y + 10), h, fill="white", font=font_header)

    # 数据行
    for ri, r in enumerate(records):
        row_y = header_y + HEADER_H + ri * ROW_H

        # 交替背景
        bg = "#F5F7FF" if ri % 2 == 0 else "white"
        draw.rectangle((12, row_y, width - 12, row_y + ROW_H), fill=bg)
        draw.line((12, row_y + ROW_H, width - 12, row_y + ROW_H), fill="#E0E0E0")

        # 状态颜色
        status_color = _COLORS.get(r.status, "#212121")
        content_disp = r.content or "-"
        time_str = datetime.fromtimestamp(r.time).strftime(fmt) if r.time else "-"
        revoke_ts = datetime.fromtimestamp(r.revoke_time).strftime(fmt) if r.revoke_time else "-"

        vals = [
            str(r.id), time_str,
            _truncate(str(r.from_group or "-"), font_cell, _COL_WIDTHS[2]),
            _truncate(str(r.sender), font_cell, _COL_WIDTHS[3]),
            r.method or "-",
            _truncate(content_disp, font_cell, _COL_WIDTHS[5]),
            _truncate(r.reason or "-", font_cell, _COL_WIDTHS[6]),
            r.status or "-",
            revoke_ts,
            _truncate(r.revoke_reason or "-", font_cell, _COL_WIDTHS[9]),
        ]

        for j, v in enumerate(vals):
            color = status_color if j == 7 else "#212121"
            draw.text((col_x[j], row_y + 10), v, fill=color, font=font_cell)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _truncate(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    w = _get_text_width(text, font)
    if w <= max_w:
        return text
    while text and _get_text_width(text + "…", font) > max_w:
        text = text[:-1]
    return text + "…" if text else "…"
