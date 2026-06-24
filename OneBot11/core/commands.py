"""
指令实现：/help, /p, /rp, /h, /a, /config
"""
import re
import time
import logging
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from .models import ConfigInfo, ConfigState, CommandItem, CommandConfig, PunishRecord, BlacklistItem
from .data_manager import DataManager
from .render import render_help, render_record_table

if TYPE_CHECKING:
    from bot.api import OneBotAPI

logger = logging.getLogger("Hollow.Cmd")

VALID_METHODS = ("kick", "mute", "warn")


class CommandHandler:
    """指令处理器"""

    def __init__(self, api: "OneBotAPI", dm: DataManager,
                 wake_words: List[str], super_admins: set[str],
                 render_enabled: bool = True):
        self.api = api
        self.dm = dm
        self.wake_words = wake_words
        self.super_admins = super_admins
        self.render_enabled = render_enabled
        self.primary_wake = wake_words[0] if wake_words else "/"

        # 多配置运行时数据
        self.configs: dict[str, ConfigState] = {}
        self._cmd_map: dict[str, str] = {}  # 外部名 → 内部命令名
        self.global_commands: CommandConfig = CommandConfig.defaults()

    # ==================== 生命周期 ====================

    def load(self):
        self.dm.check_all()
        self.configs.clear()
        self.global_commands = self.dm.load_global_commands()

        for name in self.dm.list_configs():
            info = self.dm.load_config_info(name)
            commands = self.dm.load_config_commands(name)
            records = self.dm.load_config_records(name)
            permissions = self.dm.load_config_permissions(name)
            blacklist = self.dm.load_config_blacklist(name)

            records_by_id: dict[int, PunishRecord] = {}
            max_id = 0
            for r in records:
                records_by_id[r.id] = r
                if r.id > max_id:
                    max_id = r.id

            self.configs[name] = ConfigState(
                name=name,
                info=info,
                commands=commands,
                records_by_id=records_by_id,
                permissions=permissions,
                blacklist=blacklist,
                next_rid=max_id + 1,
            )

        total_records = sum(len(c.records) for c in self.configs.values())
        logger.info(f"已加载: {len(self.configs)} 配置 {total_records} 记录")

        # 构建外部名 → 内部命令名的映射
        self._build_cmd_map()

    def _build_cmd_map(self):
        """从全局+所有配置的命令 names 构建 name→internal 映射"""
        self._cmd_map.clear()
        # 全局命令
        for internal, item in self.global_commands.commands.items():
            for n in item.names:
                if n and n not in self._cmd_map:
                    self._cmd_map[n] = internal
        # 各配置覆盖
        for cfg in self.configs.values():
            for internal, item in cfg.commands.commands.items():
                for n in item.names:
                    if n and n not in self._cmd_map:
                        self._cmd_map[n] = internal

    def save(self):
        for name, state in self.configs.items():
            self.dm.save_config(name, state)

    # ==================== 权限 ====================

    def _level(self, qq: str) -> int:
        if qq in self.super_admins:
            return 0
        # 在权限系统中查找（返回任意配置里的最高权限）
        best = -1
        for cfg in self.configs.values():
            lv = cfg.permissions.get(qq, -1)
            if lv > best:
                best = lv
        return best

    # ==================== 配置查找 ====================

    def _find_configs(self, group_id: str) -> list[ConfigState]:
        """查找包含此群的所有配置"""
        result = []
        for cfg in self.configs.values():
            if (cfg.info.notify_group and cfg.info.notify_group == group_id) or \
               group_id in cfg.info.execution_groups:
                result.append(cfg)
        return result

    def _get_config(self, name: str) -> Optional[ConfigState]:
        return self.configs.get(name)

    def _resolve_config_name(self, group_id: str, parts: List[str],
                              idx: int) -> tuple[Optional[ConfigState], int]:
        """尝试从 parts[idx] 解析配置名，若匹配则返回 (ConfigState, idx+1)"""
        if idx >= len(parts):
            return None, idx
        cfg = self._get_config(parts[idx])
        if cfg is not None:
            return cfg, idx + 1
        return None, idx

    def _require_config_for_group(self, group_id: str, cmd_name: str,
                                   config_name: Optional[str] = None) -> Optional[list[ConfigState]]:
        """
        获取当前群对应的配置列表。
        - 0 配置 → 返回 None（不响应）
        - 1 配置 → 返回该配置
        - ≥2 配置 → 若有 config_name 则返回指定配置，否则返回 None 表示需报错
        """
        configs = self._find_configs(group_id)
        if not configs:
            return None

        if config_name:
            cfg = self._get_config(config_name)
            if cfg is None:
                return None  # 配置不存在
            if cfg not in configs:
                return None  # 指定配置不包含此群
            return [cfg]

        if len(configs) >= 2:
            return None  # 需要指定配置名

        return configs

    # ==================== 命令配置检查 ====================

    def _resolved_commands(self, cfg: ConfigState) -> CommandConfig:
        """获取配置的完整命令配置（配置覆盖 + 全局回退）"""
        merged = dict(self.global_commands.commands)  # 全局作底
        merged.update(cfg.commands.commands)           # 配置覆盖
        return CommandConfig(commands=merged)

    def _get_cmd_item(self, internal: str, configs: list[ConfigState]) -> Optional[CommandItem]:
        """获取命令配置（配置优先 → 全局回退，取首个启用的）"""
        # 先在配置中查找
        for cfg in configs:
            item = cfg.commands.commands.get(internal)
            if item and item.enabled:
                return item
        # 全局回退
        item = self.global_commands.commands.get(internal)
        if item and item.enabled:
            return item
        return None

    def _get_sub_item(self, parent: CommandItem, sub_name: str) -> Optional[CommandItem]:
        """获取子命令配置"""
        if not parent.sub:
            return None
        return parent.sub.get(sub_name)

    def _resolve_min_level(self, item: CommandItem, parent: Optional[CommandItem] = None) -> int:
        """解析有效 min_level：None 则继承上级，上级也无则默认 1"""
        if item.min_level is not None:
            return item.min_level
        if parent and parent.min_level is not None:
            return parent.min_level
        return 1

    def _check_command(self, internal: str, configs: list[ConfigState],
                       user_level: int) -> bool:
        """
        检查命令是否可用。返回 True=通过，False=不响应。
        configs 为空时始终通过。
        """
        if not configs:
            return True

        item = self._get_cmd_item(internal, configs)
        if item is None:
            return False  # 未找到或全部禁用

        min_lv = self._resolve_min_level(item)
        if user_level == 0:
            return True
        if user_level == -1:
            return min_lv == -1
        return user_level <= min_lv

    def _check_sub_command(self, internal: str, sub_name: str,
                           configs: list[ConfigState], user_level: int) -> bool:
        """检查子命令是否可用"""
        if not configs:
            return True

        item = self._get_cmd_item(internal, configs)
        if item is None:
            return False

        sub = self._get_sub_item(item, sub_name)
        if sub is None:
            return False
        if not sub.enabled:
            return False

        min_lv = self._resolve_min_level(sub, item)
        if user_level == 0:
            return True
        if user_level == -1:
            return min_lv == -1
        return user_level <= min_lv

    # ==================== 消息入口 ====================

    async def handle_message(self, event: dict) -> Optional[str]:
        """处理群消息事件，返回回复文本或 None"""
        if event.get("message_type") != "group":
            return None

        raw = event.get("raw_message", event.get("message", "")).strip()
        group_id = str(event.get("group_id", ""))
        sender_id = str(event.get("user_id", ""))

        # 检查唤醒词
        triggered = False
        for w in self.wake_words:
            if raw.startswith(w):
                raw = raw[len(w):].strip()
                triggered = True
                break
        if not triggered:
            return None

        # 权限
        level = self._level(sender_id)
        if level < 0:
            return None

        parts = raw.split()
        if not parts:
            return None
        ext_cmd = parts[0].lower()

        # 从消息中提取 at 列表
        at_list = self._extract_at(event)

        # 解析外部名 → 内部名
        internal = self._cmd_map.get(ext_cmd)
        if internal is None:
            return None  # 不认识的命令，不响应

        # 命令启用 + 权限检查
        if internal in ("help", "config"):
            ok = self._check_command(internal, list(self.configs.values()), level)
        else:
            match_cfgs = self._find_configs(group_id)
            ok = self._check_command(internal, match_cfgs, level)
        if not ok:
            return None  # 禁用或权限不足，不响应

        if internal == "help":
            sender = event.get("sender", {})
            sender_card = sender.get("card", "") or sender.get("nickname", "")
            return await self._help(level, sender_id, group_id, parts, sender_card)
        elif internal == "punish":
            return await self._punish(level, sender_id, group_id, parts, at_list)
        elif internal == "revoke":
            return await self._revoke(level, sender_id, group_id, parts)
        elif internal == "history":
            return await self._query(level, group_id, parts, at_list)
        elif internal == "admin":
            return await self._permission(level, sender_id, group_id, parts, at_list)
        elif internal == "config":
            return await self._config_cmd(level, sender_id, group_id, parts)

        return None

    async def handle_notice(self, event: dict):
        """处理通知事件（成员入群 → 黑名单检查）"""
        if event.get("notice_type") != "group_increase":
            return

        group_id = str(event.get("group_id", ""))
        user_id = str(event.get("user_id", ""))

        configs = self._find_configs(group_id)
        if not configs:
            return

        uid = int(user_id)
        kicked = False
        for cfg in configs:
            for b in cfg.blacklist:
                if b.qq == uid and b.group_name == cfg.name:
                    try:
                        gid = int(group_id)
                        ok = await self.api.set_group_kick(gid, uid, reject_add_request=False)
                        if ok:
                            await self.api.send_group_msg(gid,
                                f"[CQ:at,qq={user_id}] 在配置 {cfg.name} 黑名单中，已自动移出。原因：{b.reason}")
                            kicked = True
                    except Exception as e:
                        logger.error(f"黑名单踢人异常: {e}")
                    break
            if kicked:
                break

    # ==================== 辅助 ====================

    @staticmethod
    def _extract_at(event: dict) -> List[str]:
        ats = []
        raw = event.get("raw_message", event.get("message", ""))
        for m in re.finditer(r'\[CQ:at,qq=(\d+)\]', str(raw)):
            qq = m.group(1)
            if qq and qq != "0":
                ats.append(qq)
        return ats

    @staticmethod
    def _extract_qq(text: str) -> Optional[str]:
        if not text:
            return None
        m = re.search(r'\d{5,}', text)
        return m.group() if m else None

    @staticmethod
    def _parse_duration(dur: str) -> Optional[int]:
        if not dur or not dur.strip():
            return None
        dur = dur.strip()
        try:
            return int(float(dur) * 86400)
        except ValueError:
            pass
        m = re.match(r'^(\d+d)?(\d+h)?(\d+m)?$', dur, re.I)
        if m and dur:
            total = 0
            ok = False
            if m.group(1):
                total += int(m.group(1)[:-1]) * 86400; ok = True
            if m.group(2):
                total += int(m.group(2)[:-1]) * 3600; ok = True
            if m.group(3):
                total += int(m.group(3)[:-1]) * 60; ok = True
            if ok and total > 0:
                return total
        return None

    def _resolve_target(self, at_list: List[str], text: str) -> Optional[str]:
        if at_list:
            return at_list[0]
        return self._extract_qq(text)

    async def _notify_admin(self, cfg: ConfigState, msg: str):
        """通知配置的通知群"""
        ng = cfg.info.notify_group
        if ng:
            try:
                await self.api.send_group_msg(int(ng), msg)
            except Exception as e:
                logger.error(f"通知通知群失败: {e}")

    # ==================== 图片渲染（Pillow） ====================

    def _render_png(self, maker) -> Optional[bytes]:
        if not self.render_enabled:
            return None
        try:
            return maker()
        except ImportError:
            logger.warning("Pillow 未安装，无法渲染图片")
            self.render_enabled = False
            return None
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            return None

    async def _send_image(self, group_id: int, png_bytes: bytes):
        import base64
        b64 = base64.b64encode(png_bytes).decode()
        await self.api.send_group_msg(group_id, f"[CQ:image,file=base64://{b64}]")

    # ==================== /help ====================

    _CMD_DESC = {
        "help": "查看帮助",
        "punish": "处罚成员",
        "revoke": "撤销处罚",
        "history": "查询记录",
        "admin": "权限管理",
        "config": "配置管理",
    }

    # 概览用：格式行（{cmd} 替换为配置中的第一个命令名）
    _CMD_FORMAT = {
        "help":    "{w}{cmd} [命令]",
        "punish":  "{w}{cmd} <目标> [配置] <方式> [内容] <原因>",
        "revoke":  "{w}{cmd} [配置] <记录ID> [撤销原因]",
        "history": "{w}{cmd} [配置] [目标] [-i]",
        "admin":   "{w}{cmd} [配置] <目标> [等级]",
        "config":  "{w}{cmd} <子命令>",
    }

    # 概览用：示例（{cmd} 替换为配置中的第一个命令名）
    _CMD_EXAMPLES = {
        "help":    ["{w}{cmd}", "{w}{cmd} <命令>"],
        "punish":  ["{w}{cmd} @某人 mute 1d2h 广告刷屏",
                    "{w}{cmd} 123456 kick f 严重违规"],
        "revoke":  ["{w}{cmd} 5", "{w}{cmd} 反馈组 5 误判"],
        "history": ["{w}{cmd}", "{w}{cmd} @某人 -i", "{w}{cmd} 反馈组"],
        "admin":   ["{w}{cmd} @某人 1", "{w}{cmd} 反馈组 @某人 2"],
        "config":  ["{w}{cmd} new 反馈组", "{w}{cmd} 反馈组 notify"],
    }

    # 详细帮助用：完整说明
    _CMD_DETAIL = {
        "help":    ["> {w}{cmd} [命令]", "~ {w}{cmd}  → 概览  /  {w}{cmd} <命令>  → 详情"],
        "punish":  ["> {w}{cmd} <目标> [配置] <方式> [内容] <原因>",
                    "- <目标>  @某人 或 QQ号",
                    "- [配置]  指定配置名（可选，不填=当前群所有配置）",
                    "- <方式>  kick / mute / warn",
                    "- [内容]  kick可选f(黑名单)；mute必填时长；warn不需要",
                    "- <原因>  缺失时记为不合规，不执行",
                    "# 时长格式", "- 纯数字=天  组合 1d2h30m",
                    "~ {w}{cmd} @某人 mute 1d2h 广告刷屏"],
        "revoke":  ["> {w}{cmd} [配置] <记录ID> [撤销原因]",
                    "- [配置]  多配置群必填，单配置群可选",
                    "! 仅可撤销已执行/执行失败/部分失败的记录",
                    "~ {w}{cmd} 5  /  {w}{cmd} 反馈组 5 误判"],
        "history": ["> {w}{cmd} [配置] [目标] [-i]",
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

    async def _help(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], sender_card: str = "") -> str:
        w = self.primary_wake
        configs = self._find_configs(group_id)
        is_super = (level == 0)

        # 副标题：发送者群昵称 + QQ
        if sender_card:
            subtitle = f"{sender_card} ({sender_id})"
        else:
            subtitle = f"QQ: {sender_id}"

        # 解析要查看的命令（外部名 → 内部名）
        if len(parts) >= 2:
            ext_cmd = parts[1].lower()
            detail_internal = self._cmd_map.get(ext_cmd)
            if detail_internal is None:
                known = sorted(set(self._cmd_map.values()))
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
            lines = self._build_overview_lines(w, configs, sender_id)
            title = "HollowGroupManager 帮助"

        png = self._render_png(lambda: render_help(title, subtitle, lines))
        if png:
            await self._send_image(int(group_id), png)
            return ""
        return self._help_fallback_text(w, configs, level, detail_internal)

    def _cmd_visible(self, item: Optional[CommandItem], user_level: int) -> bool:
        """命令是否对该用户可见"""
        if item is None or not item.enabled:
            return False
        min_lv = self._resolve_min_level(item)
        if user_level == 0:
            return True
        if user_level == -1:
            return min_lv == -1
        return user_level <= min_lv

    def _format_cmd_names(self, item: CommandItem, w: str) -> str:
        """格式化命令名显示，如 '{w}punish (或 {w}p)'"""
        if not item.names:
            return ""
        primary = item.names[0]
        aliases = [n for n in item.names[1:]]
        if aliases:
            return f"{w}{primary} (或 {w}{' '.join(aliases)})"
        return f"{w}{primary}"

    def _primary_cmd_name(self, item: CommandItem) -> str:
        """获取命令的第一个名称"""
        return item.names[0] if item.names else ""

    def _build_overview_lines(self, w: str, configs: list[ConfigState],
                               sender_id: str) -> list[str]:
        """按配置分组生成帮助概览"""
        lines = [
            "# 可用指令",
            f"- 唤醒词: {', '.join(self.wake_words)}",
        ]

        if not configs:
            gc = self.dm.load_global_commands()
            lines.append("# ── 全局（当前群未关联配置）──")
            lines += self._render_cmd_section(gc, -1, w)
            return lines

        lines.append(f"- 本群关联 {len(configs)} 个配置")
        lines.append("")
        for cfg in configs:
            cfg_level = 0 if sender_id in self.super_admins else cfg.permissions.get(sender_id, -1)
            lv_label = "超级管理员（0）" if cfg_level == 0 else (
                "普通成员（-1）" if cfg_level == -1 else f"管理员（{cfg_level}）")

            ng = cfg.info.notify_group or "未设"
            eg_count = len(cfg.info.execution_groups)
            lines.append(f"# ── 配置 \"{cfg.name}\" ──")
            lines.append(f"- 通知群: {ng}  |  执行群: {eg_count}个  |  记录: {len(cfg.records)}条"
                         f"  |  我的权限: {lv_label}")
            lines.append("")
            lines += self._render_cmd_section(self._resolved_commands(cfg), cfg_level, w)

            lines.append("")
        return lines

    def _render_cmd_section(self, cc: "CommandConfig",
                             user_level: int, w: str) -> list[str]:
        """渲染命令列表：格式 + 描述 + 示例"""
        lines = []
        order = ["help", "punish", "revoke", "history", "admin", "config"]
        for internal in order:
            item = cc.commands.get(internal)
            if item is None or not self._cmd_visible(item, user_level):
                continue
            primary = self._primary_cmd_name(item)
            aliases = item.names[1:] if len(item.names) > 1 else []
            desc = self._CMD_DESC.get(internal, "")
            min_str = ""
            if item.min_level is not None and item.min_level != -1:
                min_str = f"  ·需等级 {item.min_level}"

            # 格式行
            fmt = self._CMD_FORMAT.get(internal, "")
            if fmt:
                fmt = fmt.replace("{w}", w).replace("{cmd}", primary)
                lines.append(f"> {fmt}{min_str}")

            # 别名（若有）
            if aliases:
                alias_str = " ".join(f"{w}{a}" for a in aliases)
                lines.append(f"- 别名: {alias_str}")

            # 描述
            lines.append(f"- {desc}")

            # 示例（取前两个）
            examples = self._CMD_EXAMPLES.get(internal, [])
            for ex in examples[:2]:
                ex = ex.replace("{w}", w).replace("{cmd}", primary)
                lines.append(f"~ {ex}")

            lines.append("")
        return lines

    def _build_detail_lines(self, w: str, internal: str, ext_cmd: str,
                             configs: list[ConfigState]) -> list[str]:
        """生成命令的详细帮助，以用户输入的名称为主，其余为别名"""
        lines = [f"# {self._CMD_DESC.get(internal, internal)}"]

        # 获取完整的 names 列表（全局兜底）
        all_names: list[str] = []
        for cfg in configs:
            resolved = self._resolved_commands(cfg)
            item = resolved.commands.get(internal)
            if item and item.enabled and ext_cmd in item.names:
                all_names = list(item.names)
                break
        if not all_names:
            item = self.global_commands.commands.get(internal)
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
            resolved = self._resolved_commands(cfg)
            item = resolved.commands.get(internal)
            if item and item.enabled and ext_cmd in item.names:
                name_str = self._format_cmd_names(item, w)
                if name_str not in shown:
                    shown.add(name_str)
                    lv = self._resolve_min_level(item)
                    lines.append(f"- 配置 [{cfg.name}]: {name_str}  需等级: {lv}")

        if not shown:
            item = self.global_commands.commands.get(internal)
            if item and ext_cmd in item.names:
                name_str = self._format_cmd_names(item, w)
                lv = self._resolve_min_level(item)
                lines.append(f"- 全局: {name_str}  需等级: {lv}")

        # 详细用法（使用用户输入的名称）
        detail = self._CMD_DETAIL.get(internal, [])
        if detail:
            lines.append("")
            for d in detail:
                lines.append(d.replace("{w}", w).replace("{cmd}", ext_cmd))
        return lines

    def _help_fallback_text(self, w: str, configs: list[ConfigState],
                             level: int, cmd: Optional[str]) -> str:
        """纯文本回退帮助"""
        if cmd:
            detail = self._CMD_DETAIL.get(cmd, [f"{{w}}{{cmd}}"])
            detail = [d.replace("{w}", w).replace("{cmd}", cmd) for d in detail]
            return "\n".join([f"=== {cmd} 帮助 ==="] + detail)

        lines = [f"=== HollowGroupManager 帮助 ===",
                 f"唤醒词: {', '.join(self.wake_words)}", ""]
        if not configs:
            gc = self.dm.load_global_commands()
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

    # ==================== /p 处罚 ====================

    async def _punish(self, level: int, sender_id: str, group_id: str,
                      parts: List[str], at_list: List[str]) -> str:
        if len(parts) < 2:
            return "格式：<唤醒词>p <目标> [配置] <方式> [内容] <原因>"

        # 解析目标
        target_qq = self._resolve_target(at_list, parts[1])
        if not target_qq:
            return "未找到被处罚者QQ，请 @ 或输入QQ号"

        # 尝试解析配置名（parts[2] 若不是方式则视为配置名）
        cfg_name: Optional[str] = None
        method_idx = 2
        if len(parts) > 2 and parts[2].lower() not in VALID_METHODS:
            cfg_name = parts[2]
            method_idx = 3

        # 确定配置范围
        match_cfgs = self._find_configs(group_id)
        if not match_cfgs:
            return None  # 不响应

        if cfg_name:
            target_cfgs = [c for c in match_cfgs if c.name == cfg_name]
            if not target_cfgs:
                return f"配置 \"{cfg_name}\" 不存在或不包含本群"
        else:
            target_cfgs = match_cfgs

        # 解析方式和内容
        if method_idx >= len(parts):
            return "缺少处罚方式（kick / mute / warn）"
        method = parts[method_idx].lower()
        if method not in VALID_METHODS:
            return "无效处罚方式，可选：kick, mute, warn"

        content = ""
        reason_start = method_idx + 1
        if method == "mute":
            if len(parts) < method_idx + 2:
                return "禁言缺少时长"
            content = parts[method_idx + 1]
            reason_start = method_idx + 2
            if self._parse_duration(content) is None:
                return "时长格式错误，支持数字(天)或组合如1d2h30m"
        elif method == "kick":
            if len(parts) > method_idx + 1 and parts[method_idx + 1].lower() == "f":
                content = "f"
                reason_start = method_idx + 2
            else:
                reason_start = method_idx + 1

        # 原因检查
        if reason_start >= len(parts):
            # 不合规
            records_info = []
            for cfg in target_cfgs:
                r = self._add_record(cfg.name, sender_id, group_id, int(target_qq),
                                     method, content, "", "不合规")
                records_info.append((cfg, r))
                await self._notify_admin(cfg,
                    f"[不合规] 处罚（{r.id}）：发起者（{sender_id}）在群（{group_id}）"
                    f"发起的处罚缺少原因，未执行。")
            self.save()
            return "原因缺失，已记录为[不合规]，未执行处罚。"

        reason = " ".join(parts[reason_start:])

        # 收集执行群（去重）
        all_exec_groups: set[str] = set()
        for cfg in target_cfgs:
            all_exec_groups.update(cfg.info.execution_groups)

        gid_int = int(group_id)
        tid_int = int(target_qq)

        # 创建记录
        records_info: list[tuple[ConfigState, PunishRecord]] = []
        for cfg in target_cfgs:
            r = self._add_record(cfg.name, sender_id, group_id, tid_int,
                                 method, content, reason, "执行中")
            records_info.append((cfg, r))

        # 执行处罚
        any_ok = False
        any_fail = False
        fail_groups: List[str] = []

        for eg in list(all_exec_groups):
            eg_int = int(eg)
            if not await self.api.is_member_in_group(eg_int, tid_int):
                continue
            if method == "mute":
                muted = await self.api.get_muted_members(eg_int)
                for mm in muted:
                    if mm["user_id"] == tid_int:
                        for cfg, r in records_info:
                            await self._notify_admin(cfg,
                                f"[提示] 处罚「{r.id}」在群{eg}成员{target_qq}已被禁言，将更新时长。")
                        break
            try:
                if method == "kick":
                    ok = await self.api.set_group_kick(eg_int, tid_int, content == "f")
                    if not ok:
                        raise RuntimeError("踢出返回失败")
                    if content == "f":
                        for cfg in target_cfgs:
                            self._blacklist_add(cfg.name, tid_int, reason, cfg.name)
                    any_ok = True
                elif method == "mute":
                    sec = self._parse_duration(content)
                    ok = await self.api.set_group_ban(eg_int, tid_int, sec)
                    if not ok:
                        raise RuntimeError("禁言返回失败")
                    any_ok = True
                else:
                    any_ok = True
            except Exception as e:
                any_fail = True
                fail_groups.append(eg)
                for cfg, r in records_info:
                    await self._notify_admin(cfg,
                        f"[异常] 处罚「{r.id}」在群{eg}执行失败：{e}")

        # 更新状态
        fail_str = "失败群：" + ",".join(fail_groups) if fail_groups else ""
        for cfg, r in records_info:
            if any_fail and not any_ok:
                r.status = "执行失败"
                r.fail_detail = fail_str
            elif any_fail:
                r.status = "部分失败"
                r.fail_detail = fail_str
            else:
                r.status = "已执行"

        # 通知
        notified: set[str] = set()
        for cfg, r in records_info:
            ng = cfg.info.notify_group
            if ng and ng not in notified:
                notified.add(ng)
                fb = "处罚已执行。" if not fail_str else f"处罚部分失败（{fail_str}）"
                if any_fail and not any_ok:
                    fb = f"处罚执行失败（{fail_str}）"
                try:
                    await self.api.send_group_msg(int(ng),
                        f"处罚「{r.id}」：{sender_id}在{group_id}发起对"
                        f"{target_qq}的「{r.describe()}」处罚，原因：「{reason}」，"
                        f"状态：{r.status}" +
                        (f"（{r.fail_detail}）" if r.fail_detail else ""))
                except Exception:
                    pass

        self.save()

        if any_fail and not any_ok:
            return f"处罚执行失败，{fail_str}"
        elif any_fail:
            return f"处罚部分失败，{fail_str}"
        return f"处罚已执行。（{len(target_cfgs)} 配置）"

    # ==================== /rp 撤销 ====================

    async def _revoke(self, level: int, sender_id: str, group_id: str,
                      parts: List[str]) -> str:
        if len(parts) < 2:
            return "格式：/rp [配置] <记录ID> [撤销原因]"

        match_cfgs = self._find_configs(group_id)
        if not match_cfgs:
            return None

        # 解析配置名
        cfg_name: Optional[str] = None
        id_idx = 1
        cfg = self._get_config(parts[1])
        if cfg is not None:
            cfg_name = parts[1]
            id_idx = 2
        elif len(match_cfgs) >= 2:
            return "本群属于多个配置，请指定配置名称：/rp <配置名称> <记录ID> [撤销原因]"

        if id_idx >= len(parts):
            return "缺少记录ID"

        try:
            rid = int(parts[id_idx])
        except ValueError:
            return "记录ID必须为数字"

        # 查找记录
        rr = " ".join(parts[id_idx + 1:])

        if cfg_name:
            target_cfg = self._get_config(cfg_name)
            if target_cfg is None:
                return f"配置 \"{cfg_name}\" 不存在"
            target = target_cfg.records_by_id.get(rid)
            if target is None:
                return f"配置 \"{cfg_name}\" 中不存在记录 {rid}"
            cfgs_to_search = [target_cfg]
        else:
            target = None
            cfgs_to_search = match_cfgs
            for c in cfgs_to_search:
                target = c.records_by_id.get(rid)
                if target is not None:
                    break

        if target is None:
            return "记录不存在"

        # 找到记录所属配置
        owner_cfg = None
        for c in self.configs.values():
            if rid in c.records_by_id:
                owner_cfg = c
                break

        if owner_cfg is None:
            return "记录对应配置异常"

        if target.status not in ("已执行", "执行失败", "部分失败"):
            return f"状态为 {target.status}，不可撤销"

        any_ok = False
        skip: List[str] = []
        fail: List[str] = []

        if target.method == "mute":
            for eg in list(owner_cfg.info.execution_groups):
                eg_int = int(eg)
                tid_int = target.target
                try:
                    if not await self.api.is_member_in_group(eg_int, tid_int):
                        skip.append(f"{eg}(成员不存在)")
                        continue
                    ok = await self.api.set_group_ban(eg_int, tid_int, 0)
                    if ok:
                        any_ok = True
                    else:
                        fail.append(eg)
                except Exception as e:
                    fail.append(eg)
                    await self._notify_admin(owner_cfg,
                        f"[异常] 撤销（{target.id}）在群（{eg}）失败：{e}")
            if not any_ok and fail:
                return "撤销失败，失败群：" + ",".join(fail)
        elif target.method == "kick" and target.content == "f":
            self._blacklist_remove(owner_cfg.name, target.target, owner_cfg.name)
            any_ok = True

        target.status = "已撤销"
        target.revoke_time = int(time.time())
        target.revoke_reason = rr

        msg = f"记录 {rid} 已撤销"
        if skip:
            msg += "（跳过：" + ", ".join(skip) + "）"

        await self._notify_admin(owner_cfg,
            f"[撤销] 处罚（{target.id}）已被（{sender_id}）撤销，"
            f"原处罚：（{target.target}）的（{target.describe()}），"
            f"原因：（{target.reason}）。撤销原因：" + (rr or "无"))

        self.save()
        return msg

    # ==================== /h 查询 ====================

    async def _query(self, level: int, group_id: str,
                     parts: List[str], at_list: List[str]) -> str:
        match_cfgs = self._find_configs(group_id)
        if not match_cfgs:
            return None

        # 解析配置名
        cfg_name: Optional[str] = None
        rest_start = 1
        cfg = self._get_config(parts[1]) if len(parts) > 1 else None
        if cfg is not None:
            cfg_name = parts[1]
            rest_start = 2
        elif len(match_cfgs) >= 2:
            return "本群属于多个配置，请指定配置名称：/h <配置名称> [QQ用户] [-i]"

        # 确定查询的配置
        if cfg_name:
            target_cfgs = [c for c in match_cfgs if c.name == cfg_name]
            if not target_cfgs:
                return f"配置 \"{cfg_name}\" 不存在或不包含本群"
        else:
            target_cfgs = match_cfgs

        # 收集记录
        all_records: list[PunishRecord] = []
        for c in target_cfgs:
            all_records.extend(c.records)

        # 无参数 → 全表
        if len(parts) < rest_start + 1:
            return await self._render_table(all_records, group_id)

        # 解析目标
        target_qq = self._resolve_target(at_list, parts[rest_start])
        if not target_qq:
            # 可能是 -i（无目标的详情）
            if parts[rest_start] == "-i":
                return await self._render_table(all_records, group_id)
            return "未找到目标QQ"

        tid = int(target_qq)
        filtered = [r for r in all_records if r.target == tid]
        detail = len(parts) > rest_start + 1 and parts[rest_start + 1] == "-i"

        if detail:
            return await self._render_table(filtered, group_id)
        else:
            total = kick = mute_n = 0
            mute_sec = 0
            for r in filtered:
                if r.status in ("已执行", "执行失败", "部分失败"):
                    total += 1
                    if r.method == "mute":
                        mute_n += 1
                        s = self._parse_duration(r.content)
                        if s:
                            mute_sec += s
                    elif r.method == "kick":
                        kick += 1
            lines = [f"成员 {target_qq} 统计："]
            if total > 0:
                lines.append(f"被处罚总次数：{total}")
            if mute_n > 0:
                lines.append(f"被禁言次数：{mute_n}")
                d = mute_sec // 86400
                h = (mute_sec % 86400) // 3600
                m = (mute_sec % 3600) // 60
                lines.append(f"被禁言总时长：{d}d{h}h{m}m")
            if kick > 0:
                lines.append(f"被踢次数：{kick}")
            if total == 0:
                lines.append("暂无记录")
            return "\n".join(lines)

    async def _render_table(self, records: List[PunishRecord], group_id: str) -> str:
        if not records:
            return "无记录"

        png = self._render_png(lambda: render_record_table(records))
        if png:
            await self._send_image(int(group_id), png)
            return ""

        fmt = "%m-%d %H:%M"
        lines = ["记录列表：",
                 "ID | 时间 | 发起群 | 发起者 | 方式 | 内容 | 原因 | 状态 | 撤销时间 | 撤销原因"]
        for r in records:
            c = r.content or "-"
            rr = r.revoke_reason or "-"
            fg = r.from_group or "-"
            m = r.method or "-"
            rs = r.reason or "-"
            st = r.status or "-"
            rt = datetime.fromtimestamp(r.revoke_time).strftime(fmt) if r.revoke_time else "-"
            ts = datetime.fromtimestamp(r.time).strftime(fmt) if r.time else "-"
            lines.append(f"{r.id} | {ts} | {fg} | {r.sender} | {m} | {c} | {rs} | {st} | {rt} | {rr}")
        return "\n".join(lines)

    # ==================== /a 权限 ====================

    async def _permission(self, level: int, sender_id: str, group_id: str,
                          parts: List[str], at_list: List[str]) -> str:
        if level != 0:
            return "仅超级管理员可用"

        match_cfgs = self._find_configs(group_id)
        if not match_cfgs:
            return None

        # 解析配置名
        cfg_name: Optional[str] = None
        target_idx = 1
        cfg = self._get_config(parts[1]) if len(parts) > 1 else None
        if cfg is not None:
            cfg_name = parts[1]
            target_idx = 2
        elif len(match_cfgs) >= 2:
            return "本群属于多个配置，请指定配置名称：/a <配置名称> <QQ用户> [1/-1]"

        if target_idx >= len(parts):
            return "格式：/a [配置] <成员> [1/-1]"

        tqq = self._resolve_target(at_list, parts[target_idx])
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

        self.save()
        if nl == -1:
            role = "普通成员"
        else:
            role = f"权限等级 {nl}"
        return f"已设置 {tqq} 为{role} (配置: {', '.join(cfg_names)})"

    # ==================== /config 配置管理 ====================

    async def _config_cmd(self, level: int, sender_id: str, group_id: str,
                          parts: List[str]) -> str:
        if level != 0:
            return None  # 仅超管可用，不响应

        all_cfgs = list(self.configs.values())
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
            if not self._check_sub_command("config", "new", all_cfgs, level):
                return None
            if len(parts) < 3:
                return "格式：config new <名称>"
            name = parts[2]
            if not name.strip():
                return "配置名不能为空"
            if name in self.configs:
                return f"配置 \"{name}\" 已存在"
            self.configs[name] = ConfigState(name=name, info=ConfigInfo())
            self.save()
            self._build_cmd_map()
            return f"配置 \"{name}\" 创建成功"

        # config rename <旧名> <新名>
        if first == "rename":
            if not self._check_sub_command("config", "rename", all_cfgs, level):
                return None
            if len(parts) < 4:
                return "格式：config rename <旧名> <新名>"
            old_name = parts[2]
            new_name = parts[3]
            if old_name not in self.configs:
                return f"配置 \"{old_name}\" 不存在"
            if new_name in self.configs:
                return f"配置 \"{new_name}\" 已存在"

            state = self.configs.pop(old_name)
            state.name = new_name
            self.configs[new_name] = state
            self.dm.save_config(new_name, state)
            self.dm.remove_config(old_name)
            self._build_cmd_map()
            return f"配置 \"{old_name}\" 已重命名为 \"{new_name}\""

        # config <名称> <子命令>
        name = first
        if name not in self.configs:
            return f"配置 \"{name}\" 不存在，可用：config new <名称> 创建"

        if len(parts) < 3:
            return f"格式：config {name} notify / set / remove / group"

        sub = parts[2].lower()
        if not self._check_sub_command("config", sub, all_cfgs, level):
            return None

        cfg = self.configs[name]

        if sub == "notify":
            cfg.info.notify_group = group_id
            self.save()
            return f"已将本群设为配置 \"{name}\" 的通知群"

        elif sub == "set":
            cfg.info.execution_groups.add(group_id)
            self.save()
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
            self.save()
            return f"已将本群从配置 \"{name}\" 移出"

        elif sub == "group":
            ng = cfg.info.notify_group or "未设置"
            el = ", ".join(sorted(cfg.info.execution_groups)) if cfg.info.execution_groups else "无"
            return (f"配置名：{name}\n"
                    f"通知群：{ng}\n"
                    f"执行群：{el}\n"
                    f"记录数：{len(cfg.records)}")

        return f"未知子命令：{sub}"

    # ==================== 记录/黑名单操作 ====================

    def _add_record(self, cfg_name: str, sender: str, from_group: str, target: int,
                    method: str, content: str, reason: str, status: str) -> PunishRecord:
        cfg = self.configs[cfg_name]
        r = PunishRecord(id=cfg.next_rid, sender=int(sender),
                         time=int(time.time()), from_group=from_group,
                         target=target, method=method, content=content,
                         reason=reason, status=status)
        cfg.next_rid += 1
        cfg.records.append(r)
        cfg.records_by_id[r.id] = r
        return r

    def _blacklist_add(self, cfg_name: str, qq: int, reason: str, group_name: str):
        cfg = self.configs[cfg_name]
        for b in cfg.blacklist:
            if b.qq == qq and b.group_name == group_name:
                return
        cfg.blacklist.append(BlacklistItem(
            qq=qq, reason=reason, add_time=int(time.time()),
            group_name=group_name))

    def _blacklist_remove(self, cfg_name: str, qq: int, group_name: str):
        cfg = self.configs[cfg_name]
        cfg.blacklist = [b for b in cfg.blacklist
                         if not (b.qq == qq and b.group_name == group_name)]
