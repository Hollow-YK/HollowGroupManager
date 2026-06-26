"""
/config 指令 — 多配置管理。

子命令：new, rename, notify, set, remove, group
仅超级管理员可用，注册为 global_check=True。
"""
from typing import Optional, TYPE_CHECKING

from core.models import ConfigInfo, ConfigState

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher


class ConfigModule:
    """配置管理指令模块。"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: list, at_list: list, sender_card: str = "") -> Optional[str]:
        if level != 0:
            return None  # 仅超管可用，不响应

        all_cfgs = list(self.d.configs.values())
        if len(parts) < 2:
            return ("子命令：\n"
                    "  config new <名称>              — 创建新配置\n"
                    "  config rename <旧名> <新名>     — 重命名配置\n"
                    "  config <名称> notify           — 设本群为通知群\n"
                    "  config <名称> set              — 本群加入执行群\n"
                    "  config <名称> remove           — 本群移出配置\n"
                    "  config <名称> group            — 查看配置信息")

        first = parts[1].lower()

        # config new <名称>
        if first == "new":
            if not self.d._check_sub_command("config", "new", all_cfgs, level):
                return None
            if len(parts) < 3:
                return "格式：config new <名称>"
            name = parts[2]
            if not name.strip():
                return "配置名不能为空"
            if name in self.d.configs:
                return f"配置 \"{name}\" 已存在"
            self.d.configs[name] = ConfigState(name=name, info=ConfigInfo())
            self.d.save()
            self.d._build_cmd_map()
            return f"配置 \"{name}\" 创建成功"

        # config rename <旧名> <新名>
        if first == "rename":
            if not self.d._check_sub_command("config", "rename", all_cfgs, level):
                return None
            if len(parts) < 4:
                return "格式：config rename <旧名> <新名>"
            old_name = parts[2]
            new_name = parts[3]
            if old_name not in self.d.configs:
                return f"配置 \"{old_name}\" 不存在"
            if new_name in self.d.configs:
                return f"配置 \"{new_name}\" 已存在"

            state = self.d.configs.pop(old_name)
            state.name = new_name
            self.d.configs[new_name] = state
            self.d.dm.save_config(new_name, state)
            self.d.dm.remove_config(old_name)
            self.d._build_cmd_map()
            return f"配置 \"{old_name}\" 已重命名为 \"{new_name}\""

        # config <名称> <子命令>
        name = first
        if name not in self.d.configs:
            return f"配置 \"{name}\" 不存在，可用：config new <名称> 创建"

        if len(parts) < 3:
            return f"格式：config {name} notify / set / remove / group"

        sub = parts[2].lower()
        if not self.d._check_sub_command("config", sub, all_cfgs, level):
            return None

        cfg = self.d.configs[name]

        if sub == "notify":
            cfg.info.notify_group = group_id
            self.d.save()
            return f"已将本群设为配置 \"{name}\" 的通知群"

        elif sub == "set":
            cfg.info.execution_groups.add(group_id)
            self.d.save()
            return f"已将本群加入配置 \"{name}\" 的执行群"

        elif sub == "remove":
            removed = False
            if cfg.info.notify_group == group_id:
                cfg.info.notify_group = None
                removed = True
            if group_id in cfg.info.execution_groups:
                cfg.info.execution_groups.discard(group_id)
                removed = True
            if not removed:
                return f"本群不属于配置 \"{name}\""
            self.d.save()
            return f"已将本群从配置 \"{name}\" 移出"

        elif sub == "group":
            ng = cfg.info.notify_group or "未设置"
            el = ", ".join(sorted(cfg.info.execution_groups)) if cfg.info.execution_groups else "无"
            return (f"配置名：{name}\n"
                    f"通知群：{ng}\n"
                    f"执行群：{el}\n"
                    f"记录数：{len(cfg.records)}")

        return f"未知子命令：{sub}"
