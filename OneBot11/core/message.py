"""
OneBot11 消息段模型 — 文本与 CQ 码分离处理。

内部统一表示：**消息段数组**（OneBot v11 array 格式）

    {"type": "text",  "data": {"text": "你好"}}
    {"type": "at",    "data": {"qq": "123"}}
    {"type": "image", "data": {"file": "base64://..."}}

约定：

- 数组格式的 text 段是**未转义原文**，不做反转义；只有 CQ **字符串**格式才
  unescape / escape。转义只在边界做一次，中间层永远是原文。
- 要区分文本与 CQ，直接用段数组的 `type` 字段，不需要额外视图。

段数组是唯一内部表示，下面是它的三种「读法」（视图）：

| 函数 | 文本段 | CQ 段 | 无损 | 用途 |
| --- | --- | --- | --- | --- |
| `to_plain_text` | 原文 | 丢弃 | 丢 CQ | 正则匹配、答案比对 |
| `to_readable_string` | 原文 | CQ 码 | 否 | 切分命令参数、日志 |
| `to_cq_string` | 转义 | CQ 码 | 是 | 无 raw 时合成、规范化比对 |

`to_readable_string` 是**有损**的：字面文本 `[CQ:at,qq=1]` 与真正的 at 段渲染结果
相同。因此 `@` 一律用 `get_at_list`，不要从字符串里解析 CQ 语法。
"""
import re
from typing import Iterable

from .text import (
    escape_cq_param,
    escape_cq_text,
    unescape_cq_param,
    unescape_cq_text,
)

# 段数组 / 段的类型别名
Segment = dict
Message = list[Segment]

# CQ 码: [CQ:name,key=value,...]  /  [CQ:name]
# 参数值内的 `]` 与 `,` 按规范必须转义，因此这里可以安全地按 `]` 截断
_CQ_RE = re.compile(r"\[CQ:([^,\]]+)((?:,[^\]]*)?)\]")

TEXT = "text"
AT = "at"
IMAGE = "image"


# ════════════════════════════════════════════════════════════════
# 段构造
# ════════════════════════════════════════════════════════════════

def text_segment(text: str) -> Segment:
    """构造 text 段（内容为未转义原文）。"""
    return {"type": TEXT, "data": {"text": text}}


def at_segment(qq) -> Segment:
    """构造 at 段。"""
    return {"type": AT, "data": {"qq": str(qq)}}


def image_segment(file: str) -> Segment:
    """构造 image 段（file 支持 `base64://` / URL / 本地路径）。"""
    return {"type": IMAGE, "data": {"file": file}}


def to_segments(text: str) -> Message:
    """纯文本 → 单 text 段。用于把回复字符串转成 CQ 安全的段数组。"""
    return [text_segment(text)] if text else []


# ════════════════════════════════════════════════════════════════
# 解析（收到侧）
# ════════════════════════════════════════════════════════════════

def parse_cq_string(raw: str) -> Message:
    """CQ 字符串 → 段数组。文本部分反转义，CQ 参数值反转义。"""
    if not raw:
        return []

    segments: Message = []
    pos = 0
    for m in _CQ_RE.finditer(raw):
        if m.start() > pos:
            segments.append(text_segment(unescape_cq_text(raw[pos:m.start()])))

        name = m.group(1)
        data: dict = {}
        for pair in m.group(2).lstrip(",").split(","):
            if "=" in pair:
                key, value = pair.split("=", 1)
                data[key] = unescape_cq_param(value)
        segments.append({"type": name, "data": data})
        pos = m.end()

    if pos < len(raw):
        segments.append(text_segment(unescape_cq_text(raw[pos:])))
    return segments


def normalize_message(message) -> Message:
    """把任意形式的 message 归一为段数组（规范形式）。

    接受：CQ 字符串 / 段数组 / 单个段 / None。

    规范形式：**相邻的 text 段会合并**，空 text 段会被丢弃。
    这样同一个消息只有一种段数组表示，`to_cq_string` 与
    `parse_cq_string` 可以严格互逆。
    """
    if not message:
        return []
    if isinstance(message, str):
        return parse_cq_string(message)
    if isinstance(message, dict):
        message = [message]

    segments: Message = []

    def _append_text(text: str):
        if not text:
            return
        if segments and segments[-1]["type"] == TEXT:
            segments[-1]["data"]["text"] += text
        else:
            segments.append(text_segment(text))

    for seg in message:
        if isinstance(seg, str):
            for sub in parse_cq_string(seg):
                if sub["type"] == TEXT:
                    _append_text(sub["data"]["text"])
                else:
                    segments.append(sub)
            continue
        if not isinstance(seg, dict):
            continue

        seg_type = seg.get("type") or TEXT
        data = seg.get("data")
        if not isinstance(data, dict):
            data = {"text": "" if data is None else str(data)}

        if seg_type == TEXT:
            _append_text(data.get("text", ""))
        else:
            segments.append({"type": seg_type, "data": data})
    return segments


def message_from_event(event: dict) -> Message:
    """从事件中取出消息并归一为段数组。

    优先用 `message`（段数组，最精确，无需解析）；
    否则用 `raw_message`（CQ 字符串）；最后回退到 `message` 字符串。
    """
    message = event.get("message")
    if isinstance(message, list):
        return normalize_message(message)
    raw = event.get("raw_message")
    if raw:
        return normalize_message(raw)
    return normalize_message(message or "")


# ════════════════════════════════════════════════════════════════
# 视图 / 序列化（发出侧）
# ════════════════════════════════════════════════════════════════

def iter_text(message) -> Iterable[str]:
    """遍历所有 text 段内容。"""
    for seg in normalize_message(message):
        if seg["type"] == TEXT:
            yield seg["data"].get("text", "")


def to_plain_text(message) -> str:
    """段数组 → 纯文本（只保留 text 段，丢弃 CQ 段）。

    适用于：正则匹配、答案比对、日志等只关心文字的场合。
    """
    return "".join(iter_text(message))


def segment_to_cq(segment: Segment) -> str:
    """单个段 → CQ 码字符串（text 段转义、参数值转义）。"""
    seg_type = segment.get("type") or TEXT
    data = segment.get("data") or {}

    if seg_type == TEXT:
        return escape_cq_text(data.get("text", ""))

    if not data:
        return f"[CQ:{seg_type}]"
    pairs = ",".join(
        f"{k}={escape_cq_param(str(v))}" for k, v in data.items()
    )
    return f"[CQ:{seg_type},{pairs}]"


def to_cq_string(message) -> str:
    """段数组 → CQ 字符串（text 段转义）。**无损**，`parse_cq_string` 的逆。

    不变量：`parse_cq_string(to_cq_string(m)) == normalize_message(m)`

    用于**手上没有 raw 的场合**：数组格式事件、代码构造 / 修改过的段数组、
    需要规范化形态比对。若只是原样透传未修改的 `raw_message`，直接用 raw 即可。
    """
    return "".join(segment_to_cq(seg) for seg in normalize_message(message))


def to_readable_string(message) -> str:
    """段数组 → 命令解析 / 日志用的**可读**字符串。

    text 段**原样**（不转义，便于直接取命令参数），CQ 段序列化为 CQ 码。

    注意这是**有损**视图：字面文本 `[CQ:at,qq=1]` 与真正的 at 段渲染结果相同，
    因此 `@` 名单请用 `get_at_list`，不要从这里解析 CQ 语法。
    """
    return "".join(
        seg["data"].get("text", "") if seg["type"] == TEXT
        else segment_to_cq(seg)
        for seg in normalize_message(message)
    )


def get_at_list(message) -> list[str]:
    """段数组 → 被 at 的 QQ 列表（`qq=0` 表示全体，忽略）。"""
    ats = []
    for seg in normalize_message(message):
        if seg["type"] != AT:
            continue
        qq = str(seg["data"].get("qq", ""))
        if qq and qq != "0":
            ats.append(qq)
    return ats
