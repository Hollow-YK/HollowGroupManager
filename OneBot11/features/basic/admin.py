"""
/a 指令 — 权限管理。

设置成员在某配置中的权限等级。
仅超级管理员可用。
"""
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher


class AdminModule:
    """权限管理指令模块。"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: list, at_list: list, sender_card: str = "") -> Optional[str]:
        if level != 0:
            return "仅超级管理员可用"

        match_cfgs = self.d._find_configs(group_id)
        if not match_cfgs:
            return None

        # 解析配置名
        cfg_name: Optional[str] = None
        target_idx = 1
        cfg = self.d._get_config(parts[1]) if len(parts) > 1 else None
        if cfg is not None:
            cfg_name = parts[1]
            target_idx = 2
        elif len(match_cfgs) >= 2:
            return "本群属于多个配置，请指定配置名称：/a <配置名称> <QQ用户> [1/-1]"

        if target_idx >= len(parts):
            return "格式：/a [配置] <成员> [1/-1]"

        tqq = self.d._resolve_target(at_list, parts[target_idx])
        if not tqq:
            return "未找到目标QQ"
        if tqq == sender_id:
            return "不能修改自己的权限"

        nl = 1
        if len(parts) >= target_idx + 2:
            try:
                nl = int(parts[target_idx + 1])
            except ValueError:
                return "权限必须为数字（-1=普通成员，0 不可设，≥1 数字越大权限越低）"
        if nl < -1 or nl == 0:
            return "权限值无效（-1=普通成员，≥1 数字越大权限越低，0 不可设）"

        # 确定要设置的配置
        if cfg_name:
            target_cfgs = [c for c in match_cfgs if c.name == cfg_name]
            if not target_cfgs:
                return f"配置 \"{cfg_name}\" 不存在或不包含本群"
        else:
            target_cfgs = match_cfgs

        cfg_names = []
        for c in target_cfgs:
            c.permissions[tqq] = nl
            cfg_names.append(c.name)

        self.d.save()
        if nl == -1:
            role = "普通成员"
        else:
            role = f"权限等级 {nl}"
        return f"已设置 {tqq} 为{role} (配置: {', '.join(cfg_names)})"
