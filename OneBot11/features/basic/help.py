"""
/help 指令 — 帮助系统。

显示命令概览或详细帮助，支持 Pillow 图片渲染和纯文本回退。
"""
from typing import Optional, List, TYPE_CHECKING

from features.render import render_help

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher


class HelpModule:
    """帮助指令模块。注册为 global_check=True，在所有配置中检查权限。"""

    _CMD_DESC = {
        "help": "查看帮助",
        "punish_do": "处罚成员",
        "punish_revoke": "撤销处罚",
        "punish_history": "查询处罚记录",
        "admin": "权限管理",
        "config": "配置管理",
    }

    # 概览用：格式行（{cmd} 替换为配置中的第一个命令名）
    _CMD_FORMAT = {
        "help":    "{w}{cmd} [命令]",
        "punish_do":  "{w}{cmd} <目标> [配置] <方式> [内容] <原因>",
        "punish_revoke":  "{w}{cmd} [配置] <记录ID> [撤销原因]",
        "punish_history": "{w}{cmd} [配置] [目标] [-i]",
        "admin":   "{w}{cmd} [配置] <目标> [等级]",
        "config":  "{w}{cmd} <子命令>",
    }

    # 概览用：示例（{cmd} 替换为配置中的第一个命令名）
    _CMD_EXAMPLES = {
        "help":    ["{w}{cmd} <命令>"],
        "punish_do":  ["{w}{cmd} @某人 mute 1d2h 广告刷屏"],
        "punish_revoke":  ["{w}{cmd} 5 误判"],
        "punish_history": ["{w}{cmd} @某人 -i"],
        "admin":   ["{w}{cmd} @某人 1"],
        "config":  ["{w}{cmd} new 反馈组", "{w}{cmd} 反馈组 set"],
    }

    # 详细帮助用：完整说明
    _CMD_DETAIL = {
        "help":    ["> {w}{cmd} [命令]", "~ {w}{cmd}  → 概览", "~ {w}{cmd} <命令>  → 详情"],
        "punish_do":  ["> {w}{cmd} <目标> [配置] <方式> [内容] <原因>",
                    "- <目标>  @某人 或 QQ号",
                    "- [配置]  指定配置名（可选，不填=当前群所有配置）",
                    "- <方式>  kick / mute / warn",
                    "- [内容]  kick可选f(黑名单)；mute必填时长；warn不需要",
                    "- <原因>  缺失时记为不合规，不执行",
                    "# 时长格式", "- 纯数字=天  组合 1d2h30m",
                    "~ {w}{cmd} @某人 mute 1d2h 广告刷屏"],
        "punish_revoke":  ["> {w}{cmd} [配置] <记录ID> [撤销原因]",
                    "- [配置]  多配置群必填，单配置群可选",
                    "! 仅可撤销已执行/执行失败/部分失败的记录",
                    "~ {w}{cmd} 5  /  {w}{cmd} 反馈组 5 误判"],
        "punish_history": ["> {w}{cmd} [配置] [目标] [-i]",
                    "- [配置]  指定配置名（多配置群必填）",
                    "- 无参数  全部记录表格  /  -i  图片详情",
                    "! 状态颜色：绿已执行 橙已撤销 红失败 灰不合规"],
        "admin":   ["> {w}{cmd} [配置] <目标> [等级]",
                    "- -1=普通成员  ≥1 数字越大权限越低（默认1）",
                    "! 不可设0，不可改自己",
                    "~ {w}{cmd} @某人 1  /  {w}{cmd} 反馈组 @某人 2"],
        "config":  ["> {w}{cmd} new <名称>         创建新配置",
                    "> {w}{cmd} rename <旧> <新>    重命名配置",
                    "> {w}{cmd} <名称> notify      设本群为通知群",
                    "> {w}{cmd} <名称> set         本群加入执行群",
                    "> {w}{cmd} <名称> remove      本群移出配置",
                    "> {w}{cmd} <名称> group       查看配置信息",
                    "! 一个群可属于多个配置，通知群也可设为执行群"],
    }

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    # ========== 指令入口 ==========

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        w = self.d.primary_wake
        configs = self.d._find_configs(group_id)
        is_super = (level == 0)

        # 副标题：发送者群昵称 + QQ
        if sender_card:
            subtitle = f"{sender_card} ({sender_id})"
        else:
            subtitle = f"QQ: {sender_id}"

        # 解析要查看的命令（外部名 → 内部名）
        if len(parts) >= 2:
            ext_cmd = parts[1].lower()
            detail_internal = self.d._cmd_map.get(ext_cmd)
            if detail_internal is None:
                known = sorted(set(self.d._cmd_map.values()))
                return f"未知命令：{ext_cmd}，可用：{', '.join(known)}"
            if detail_internal in ("admin", "config") and not is_super:
                return None  # 不响应
        else:
            ext_cmd = None
            detail_internal = None

        if detail_internal:
            lines = self._build_detail_lines(w, detail_internal, ext_cmd, configs)
            title = f"帮助 — {ext_cmd}"
        else:
            lines = self._build_overview_lines(w, configs, sender_id, level)
            title = "HollowGroupManager 帮助"

        png = self.d._render_png(lambda: render_help(title, subtitle, lines))
        if png:
            await self.d.send_image(int(group_id), png)
            return ""
        return self._help_fallback_text(w, configs, level, detail_internal)

    # ========== 可见性检查 ==========

    def _cmd_visible(self, item, user_level: int) -> bool:
        """命令是否对该用户可见"""
        if item is None or not item.enabled:
            return False
        min_lv = self.d._resolve_min_level(item)
        if user_level == 0:
            return True
        if user_level == -1:
            return min_lv == -1
        return user_level <= min_lv

    def _format_cmd_names(self, item, w: str) -> str:
        """格式化命令名显示，如 '{w}punish (或 {w}p)'"""
        if not item.names:
            return ""
        primary = item.names[0]
        aliases = [n for n in item.names[1:]]
        if aliases:
            return f"{w}{primary} (或 {w}{' '.join(aliases)})"
        return f"{w}{primary}"

    def _primary_cmd_name(self, item) -> str:
        """获取命令的第一个名称"""
        return item.names[0] if item.names else ""

    # ========== 概览 ==========

    def _build_overview_lines(self, w: str, configs: list,
                               sender_id: str, level: int) -> list[str]:
        """概览：全局卡片 + 有自定义的配置各一卡片"""
        lines = [
            "= 可用指令",
            f"- 唤醒词: {', '.join(self.d.wake_words)}",
        ]

        if not configs:
            lines.append("@")
            lines.append("= ── 全局（当前群未关联配置）──")
            # 无配置群：help/config 始终显示（引导设置），其余按实际权限
            lines += self._render_filtered_cmds(self.d.global_commands,
                {"help", "punish_do", "punish_revoke", "punish_history", "admin", "config"},
                level, w, force_visible={"help", "config"})
            lines.append("@@")
            return lines

        lines.append(f"- 本群关联 {len(configs)} 个配置")
        lines.append("")

        ORDER = ["help", "punish_do", "punish_revoke", "punish_history", "admin", "config"]

        # 分析每个命令在各配置中的自定义情况
        customized_by: dict[str, set[str]] = {cmd: set() for cmd in ORDER}
        for cfg in configs:
            for cmd in ORDER:
                if cfg.commands.commands.get(cmd) is not None:
                    customized_by[cmd].add(cfg.name)

        # 全局卡片：包含至少一个配置未自定义的命令（使用全局设定）
        global_card_cmds = set()
        per_cfg_cmds: dict[str, set[str]] = {cfg.name: set() for cfg in configs}
        for cmd in ORDER:
            custom_cfgs = customized_by[cmd]
            all_names = {cfg.name for cfg in configs}
            if custom_cfgs != all_names:
                # 有配置使用全局 → 放入全局卡片
                global_card_cmds.add(cmd)
            for cfg_name in custom_cfgs:
                per_cfg_cmds[cfg_name].add(cmd)

        # 对发送者在各配置中的等级
        def cfg_level(cfg):
            return 0 if sender_id in self.d.super_admins else cfg.permissions.get(sender_id, -1)

        # 全局卡片
        if global_card_cmds:
            # 用户在各配置中的最佳等级
            levels = [cfg_level(cfg) for cfg in configs]
            best_level = 0 if 0 in levels else max(levels)
            lines.append("@")
            lines.append("= ── 全局 ──")
            lines += self._render_filtered_cmds(self.d.global_commands, global_card_cmds, best_level, w)
            lines.append("@@")
            lines.append("")

        # 各配置卡片（含该配置自定义的命令，无自定义则空卡片）
        for cfg in configs:
            my_cmds = per_cfg_cmds[cfg.name]
            level = cfg_level(cfg)
            lv_label = "超级管理员（0）" if level == 0 else (
                "普通成员（-1）" if level == -1 else f"管理员（{level}）")
            ng = cfg.info.notify_group or "未设"
            eg_count = len(cfg.info.execution_groups)
            lines.append("@")
            lines.append(f"= ── 配置 \"{cfg.name}\" ──")
            lines.append(f"- 通知群: {ng}  |  执行群: {eg_count}个  |  记录: {len(cfg.records)}条"
                         f"  |  我的权限: {lv_label}")
            lines.append("")
            resolved = self.d._resolved_commands(cfg)
            lines += self._render_filtered_cmds(resolved, my_cmds, level, w)
            lines.append("@@")
            lines.append("")
        return lines

    def _render_filtered_cmds(self, cc, include: set[str],
                               user_level: int, w: str,
                               force_visible: set = None) -> list[str]:
        """渲染指定命令列表（仅 included 中的），格式 + 描述 + 示例。
        force_visible 中的命令忽略可见性检查，始终渲染。"""
        if force_visible is None:
            force_visible = set()
        lines = []
        order = ["help", "punish_do", "punish_revoke", "punish_history", "admin", "config"]
        for internal in order:
            if internal not in include:
                continue
            item = cc.commands.get(internal)
            if item is None:
                continue
            if not self._cmd_visible(item, user_level) and internal not in force_visible:
                continue
            primary = self._primary_cmd_name(item)
            aliases = item.names[1:] if len(item.names) > 1 else []
            desc = self._CMD_DESC.get(internal, "")
            min_str = ""
            if item.min_level is not None and item.min_level != -1:
                min_str = f"  ·需等级 {item.min_level}"

            fmt = self._CMD_FORMAT.get(internal, "")
            if fmt:
                fmt = fmt.replace("{w}", w).replace("{cmd}", primary)
                lines.append(f"> {fmt}{min_str}")
            if aliases:
                lines.append(f"- 别名: {' '.join(f'{w}{a}' for a in aliases)}")
            lines.append(f"- {desc}")
            examples = self._CMD_EXAMPLES.get(internal, [])
            for ex in examples[:2]:
                lines.append(f"~ {ex.replace('{w}', w).replace('{cmd}', primary)}")
            lines.append("")
        return lines

    # ========== 详细帮助 ==========

    def _build_detail_lines(self, w: str, internal: str, ext_cmd: str,
                             configs: list) -> list[str]:
        """生成命令的详细帮助，以用户输入的名称为主，其余为别名"""
        lines = [f"# {self._CMD_DESC.get(internal, internal)}"]

        # 获取完整的 names 列表（全局兜底）
        all_names: list[str] = []
        for cfg in configs:
            resolved = self.d._resolved_commands(cfg)
            item = resolved.commands.get(internal)
            if item and item.enabled and ext_cmd in item.names:
                all_names = list(item.names)
                break
        if not all_names:
            item = self.d.global_commands.commands.get(internal)
            if item:
                all_names = list(item.names)

        # 别名行（除用户输入外的名字）
        aliases = [n for n in all_names if n != ext_cmd]
        if aliases:
            alias_str = " ".join(f"{w}{a}" for a in aliases)
            lines.append(f"- 别名: {alias_str}")

        # 收集各配置中显式设置了该命令的（仅配置自己，不包含全局继承）
        shown = set()
        for cfg in configs:
            own = cfg.commands.commands.get(internal)
            if own is None:
                continue
            # 使用 resolved 获取最终名称和权限
            resolved = self.d._resolved_commands(cfg)
            item = resolved.commands.get(internal)
            if item and item.enabled and ext_cmd in item.names:
                name_str = self._format_cmd_names(item, w)
                if name_str not in shown:
                    shown.add(name_str)
                    lv = self.d._resolve_min_level(item)
                    lines.append(f"- 配置 [{cfg.name}]: {name_str}  需等级: {lv}")

        if not shown:
            item = self.d.global_commands.commands.get(internal)
            if item and ext_cmd in item.names:
                name_str = self._format_cmd_names(item, w)
                lv = self.d._resolve_min_level(item)
                lines.append(f"- 全局: {name_str}  需等级: {lv}")

        # 详细用法（使用用户输入的名称）
        detail = self._CMD_DETAIL.get(internal, [])
        if detail:
            lines.append("")
            for d in detail:
                lines.append(d.replace("{w}", w).replace("{cmd}", ext_cmd))
        return lines

    # ========== 纯文本回退 ==========

    def _help_fallback_text(self, w: str, configs: list,
                             level: int, cmd: Optional[str]) -> str:
        """纯文本回退帮助"""
        if cmd:
            detail = self._CMD_DETAIL.get(cmd, [f"{{w}}{{cmd}}"])
            detail = [d.replace("{w}", w).replace("{cmd}", cmd) for d in detail]
            return "\n".join([f"=== {cmd} 帮助 ==="] + detail)

        lines = [f"=== HollowGroupManager 帮助 ===",
                 f"唤醒词: {', '.join(self.d.wake_words)}", ""]
        if not configs:
            gc = self.d.dm.load_global_commands()
            for internal, item in gc.commands.items():
                if self._cmd_visible(item, level):
                    lines.append(
                        f"{self._format_cmd_names(item, w)}  {self._CMD_DESC.get(internal, '')}")
        else:
            for cfg in configs:
                lines.append(f"── 配置 {cfg.name} ──")
                for internal, item in cfg.commands.commands.items():
                    if self._cmd_visible(item, level):
                        lines.append(
                            f"{self._format_cmd_names(item, w)}  {self._CMD_DESC.get(internal, '')}")
        return "\n".join(lines)
