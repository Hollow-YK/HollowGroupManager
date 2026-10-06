"""
OneBot11 CQ 转义 / 反转义（低层工具）。

CQ 码「字符串格式」规定特殊字符必须转义，否则与 CQ 码语法歧义：

    纯文本（CQ 码之外）      CQ 码参数值（`[CQ:...]` 之内）
    &  → &amp;               &  → &amp;
    [  → &#91;               [  → &#91;
    ]  → &#93;               ]  → &#93;
                             ,  → &#44;

约定：**收到的先 unescape，要发出去的纯文本先 escape**。
高层封装见 `core/message.py`（消息段模型），业务代码一般不应直接调用本模块。
"""
import re

# 实体 → 原字符（唯一事实来源）
_CQ_ENTITIES: dict[str, str] = {
    "&amp;": "&",
    "&#91;": "[",
    "&#93;": "]",
    "&#44;": ",",
}

# 纯文本转义只涉及这三个（`,` 在 CQ 码外无需转义）
_CQ_TEXT_ENTITIES = ("&amp;", "&#91;", "&#93;")

# 一次扫描匹配所有实体 → 天然避免 `&amp;#91;` 被二次反转义
_CQ_TEXT_RE = re.compile("|".join(re.escape(e) for e in _CQ_TEXT_ENTITIES))
_CQ_PARAM_RE = re.compile("|".join(re.escape(e) for e in _CQ_ENTITIES))

# str.translate 单次扫描 → 不会把刚生成的 `&` 再转义一次
_CQ_TEXT_TABLE: dict[int, str] = {
    ord(_CQ_ENTITIES[e]): e for e in _CQ_TEXT_ENTITIES
}
_CQ_PARAM_TABLE: dict[int, str] = {
    ord(char): entity for entity, char in _CQ_ENTITIES.items()
}


def _unescape(text: str, pattern: re.Pattern) -> str:
    return pattern.sub(lambda m: _CQ_ENTITIES[m.group(0)], text)


def unescape_cq_text(text: str) -> str:
    """反转义纯文本（CQ 码之外的文本）。`&#44;` 不处理。"""
    if not text or "&" not in text:
        return text
    return _unescape(text, _CQ_TEXT_RE)


def unescape_cq_param(text: str) -> str:
    """反转义 CQ 码参数值（额外处理 `&#44;` → `,`）。"""
    if not text or "&" not in text:
        return text
    return _unescape(text, _CQ_PARAM_RE)


def escape_cq_text(text: str) -> str:
    """转义为纯文本（CQ 码之外的文本）。"""
    if not text:
        return text
    return text.translate(_CQ_TEXT_TABLE)


def escape_cq_param(text: str) -> str:
    """转义为 CQ 码参数值（额外处理 `,` → `&#44;`）。"""
    if not text:
        return text
    return text.translate(_CQ_PARAM_TABLE)
