"""
Pillow 图片渲染 — 替代 HTML+Playwright，轻量 ~5MB。
直接画布绘制帮助图片和记录表格，与 Java 原版 Canvas 方式一致。
"""
from io import BytesIO
from typing import Optional, List

from PIL import Image, ImageDraw, ImageFont

from core.models import PunishRecord

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
    """渲染帮助图片，返回 PNG 字节。@ 前缀标记卡片起始。"""
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

    # 行高常量
    HEIGHTS = {'#': 42, '>': 38, '-': 34, '~': 30, '!': 34, '@': 0, '=': 42}

    # 第一遍：计算高度，记录各行 y 位置
    row_y: list[tuple[int, str, str, str]] = []  # (y, prefix, text, raw)
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
        text = line[2:] if len(line) > 2 else ""
        row_y.append((y, prefix, text, line))  # 保留完整原文用于 @ 判断
        y += HEIGHTS.get(prefix, 34)

    # 找出卡片范围：`@` 开始，`@@` 结束
    PAD = 10
    card_margin = 16  # 卡片到图片左右边距
    cards: list[tuple[int, int]] = []  # (start_y, end_y)
    in_card: list[bool] = []
    card_start: Optional[int] = None
    for ry, rp, text, raw in row_y:
        if rp == '@':
            if raw == "@@":
                if card_start is not None:
                    cards.append((card_start, ry - 8))
                card_start = None
            else:
                card_start = ry
            in_card.append(False)
            continue
        in_card.append(card_start is not None)
    if card_start is not None:
        last_ry, last_pf, _, _ = row_y[-1]
        cards.append((card_start, last_ry + HEIGHTS.get(last_pf, 34) - 4))

    # 尾部声明
    footer_y = y + 8
    footer_h = 56
    height = y + footer_h + 20

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # ---- 绘制卡片背景（左右对称边距） ----
    card_bg = "#F5F7FF"
    card_border = "#D6DBF0"
    card_x0 = card_margin
    card_x1 = width - card_margin
    for cy0, cy1 in cards:
        draw.rounded_rectangle(
            (card_x0, cy0 - PAD, card_x1, cy1 + PAD),
            radius=14, fill=card_bg, outline=card_border, width=1,
        )

    # 标题
    draw.text((left_pad, 16), title, fill="#1A237E", font=font_title)

    # 副标题
    if subtitle:
        draw.text((left_pad, 50), subtitle, fill="#757575", font=font_sub)

    # 分隔线
    draw.line((left_pad, div_y, width - right_pad, div_y), fill="#E0E0E0", width=2)

    # ---- 绘制文字 ----
    for i, (ry, prefix, text, _) in enumerate(row_y):
        if prefix == '@':
            continue
        indent = 0 if prefix in ('#', '>') else 20
        if in_card[i]:
            indent += PAD

        if prefix == '=':
            tw = _get_text_width(text, font_section)
            draw.text(((width - tw) / 2, ry), text, fill="#1565C0", font=font_section)
        elif prefix == '#':
            draw.text((left_pad + indent, ry), text, fill="#1565C0", font=font_section)
        elif prefix == '>':
            draw.text((left_pad + indent, ry), text, fill="#1A237E", font=font_cmd)
        elif prefix == '-':
            draw.text((left_pad + indent, ry), text, fill="#212121", font=font_desc)
        elif prefix == '~':
            draw.text((left_pad + indent, ry), text, fill="#757575", font=font_example)
        elif prefix == '!':
            draw.text((left_pad + indent, ry), text, fill="#E65100", font=font_warn)
        else:
            draw.text((left_pad + indent, ry), text, fill="#212121", font=font_desc)

    # ---- 尾部声明 ----
    draw.line((left_pad, footer_y, width - right_pad, footer_y), fill="#E0E0FF", width=2)
    footer_font = _get_font(16, bold=False)
    line1 = "License: GNU AGPL v3.0"
    line2 = "https://github.com/Hollow-YK/HollowGroupManager"
    tw1 = _get_text_width(line1, footer_font)
    tw2 = _get_text_width(line2, footer_font)
    draw.text(((width - tw1) / 2, footer_y), line1, fill="#9E9EBB", font=footer_font)
    draw.text(((width - tw2) / 2, footer_y + 22), line2, fill="#9E9EBB", font=footer_font)

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


# ---- 配置列表表格 ----


def render_config_list(configs: list[tuple[str, str, str, int]]) -> bytes:
    """渲染配置列表表格图片，返回 PNG 字节。
    configs: [(名称, 通知群, 执行群列表, 记录数), ...]"""
    font_title = _get_font(28, bold=True)
    font_header = _get_font(18, bold=True)
    font_cell = _get_font(17, bold=False)

    _HEADERS = ["配置名", "通知群", "执行群", "记录数"]
    _COL_WIDTHS = [120, 160, 200, 90]
    ROW_H = 42
    HEADER_H = 46

    # 计算列 X 位置
    col_x = []
    x = 16
    for w in _COL_WIDTHS:
        col_x.append(x)
        x += w + 12
    width = x + 16
    header_y = 68
    height = header_y + HEADER_H + len(configs) * ROW_H + 30

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # 标题
    draw.text((20, 20), f"配置列表 ({len(configs)}个)",
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
    for ri, (name, notify, exec_groups, count) in enumerate(configs):
        row_y = header_y + HEADER_H + ri * ROW_H

        # 交替背景
        bg = "#F5F7FF" if ri % 2 == 0 else "white"
        draw.rectangle((12, row_y, width - 12, row_y + ROW_H), fill=bg)
        draw.line((12, row_y + ROW_H, width - 12, row_y + ROW_H), fill="#E0E0E0")

        vals = [
            _truncate(name, font_cell, _COL_WIDTHS[0]),
            _truncate(notify, font_cell, _COL_WIDTHS[1]),
            _truncate(exec_groups, font_cell, _COL_WIDTHS[2]),
            str(count),
        ]

        for j, v in enumerate(vals):
            draw.text((col_x[j], row_y + 10), v, fill="#212121", font=font_cell)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---- 验证题目卡片 ----

def render_question_card(expression: str, attempts: int, max_attempts: int,
                          progress: str = "", footer: str = "") -> bytes:
    """渲染验证题目卡片。expression 为题目文本（计算题算式或问答题文本）。"""
    width, padding = 460, 24
    font_q = _get_font(22, bold=True)
    font_body = _get_font(17, bold=False)
    font_small = _get_font(15, bold=False)

    # 预计算文本行
    lines: list[tuple[str, object, str]] = []  # (text, font, color)

    if progress:
        lines.append((progress, font_small, "#666666"))
        lines.append(("", font_small, "#666666"))

    lines.append(("📝 请回答以下题目", font_small, "#888888"))
    lines.append(("", font_small, "#888888"))
    lines.append((expression, font_q, "#1A237E"))

    if footer:
        lines.append(("", font_small, "#666666"))
        lines.append((footer, font_small, "#666666"))

    # 尝试次数
    if max_attempts == -1:
        attempts_str = f"尝试次数: {attempts} / 不限"
    else:
        attempts_str = f"尝试次数: {attempts} / {max_attempts + 1}"
    lines.append(("", font_small, "#666666"))
    lines.append((attempts_str, font_small, "#E65100" if attempts > 0 else "#888888"))

    # 计算高度
    line_heights = []
    total_h = padding
    for text, font, _ in lines:
        if not text:
            h = 6
        else:
            try:
                h = int(font.getbbox(text)[3] - font.getbbox(text)[1]) + 4
            except AttributeError:
                h = font.size + 4
        line_heights.append(h)
        total_h += h
    total_h += padding

    img = Image.new("RGB", (width, total_h), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    # 顶部色条
    draw.rectangle((0, 0, width, 4), fill="#1565C0")

    y = padding
    for (text, font, color), h in zip(lines, line_heights):
        if not text:
            y += h
            continue
        draw.text((padding, y), text, fill=color, font=font)
        y += h

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


# ---- 验证答题说明图片 ----

def render_verify_guide() -> bytes:
    """渲染进群验证答题说明图片。"""
    width, height = 480, 320
    img = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    font_title = _get_font(24, bold=True)
    font_body = _get_font(18, bold=False)
    font_example = _get_font(16, bold=False)

    # 标题
    title = "📋 答题说明"
    draw.text((30, 20), title, fill="#1a1a2e", font=font_title)

    # 分隔线
    draw.line((30, 55, width - 30, 55), fill="#E0E0E0", width=1)

    lines = [
        ("• 直接输入答案发送即可，无需加任何前缀", font_body, "#333333"),
        ("", font_body, "#333333"),
        ("计算题", font_title, "#16213e"),
        ("  输入计算结果数字（除法只保留整数部分，小数部分去尾）", font_body, "#555555"),
        ("  例: 3 + 5 = ? → 8", font_example, "#888888"),
        ("      7 / 2 = ? → 3", font_example, "#888888"),
        ("", font_body, "#333333"),
        ("问答题", font_title, "#16213e"),
        ("  按题目要求输入答案文本", font_body, "#555555"),
        ("  例: 群规是什么?  →  回复对应内容", font_example, "#888888"),
        ("", font_body, "#333333"),
        ("自选题", font_title, "#16213e"),
        ("  输入数字序号选择题目作答", font_body, "#555555"),
        ("", font_body, "#333333"),
        ("⚠ 每题有尝试次数限制，请认真作答", font_example, "#CC6600"),
    ]

    y = 70
    for text, font, color in lines:
        if not text:
            y += 4
            continue
        draw.text((30, y), text, fill=color, font=font)
        try:
            y += int(font.getbbox(text)[3] - font.getbbox(text)[1]) + 6
        except AttributeError:
            y += font.size + 6

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
