"""
指令/事件注册 + 分发核心 + 统一 Bot 能力 API。

功能模块的唯一依赖入口 —— 不包含任何具体命令的实现逻辑。
"""
import re
import time
import logging
from typing import Optional, List, Callable, Awaitable, TYPE_CHECKING

from .models import ConfigInfo, ConfigState, CommandItem, CommandConfig, PunishRecord, BlacklistItem
from .data_manager import DataManager

if TYPE_CHECKING:
    from bot.api import OneBotAPI

logger = logging.getLogger("Hollow.Cmd")

# 统一处理器签名
CmdHandler = Callable[[int, str, str, list, list, str], Awaitable[Optional[str]]]
EventListener = Callable[[dict], Awaitable[None]]


class CommandDispatcher:
    """OneBot11 框架中枢 — 提供注册接口 + Bot 能力 API + 框架服务。"""

    # ════════════════════════════════════════════════════════════
    # 构造函数
    # ════════════════════════════════════════════════════════════

    def __init__(self, api: "OneBotAPI", dm: DataManager,
                 wake_words: List[str], super_admins: set[str],
                 render_enabled: bool = True):
        # ── 内部依赖 ──
        self._api = api
        self.dm = dm
        self.render_enabled = render_enabled

        # ── 配置状态 ──
        self.wake_words = wake_words
        self.super_admins = super_admins
        self.primary_wake = wake_words[0] if wake_words else "/"

        # ── 多配置运行时数据 ──
        self.configs: dict[str, ConfigState] = {}
        self._cmd_map: dict[str, str] = {}  # 外部名 → 内部命令名
        self.global_commands: CommandConfig = CommandConfig.defaults()

        # ── 注册表 ──
        self._commands: dict[str, CmdHandler] = {}
        self._global_commands_set: set[str] = set()
        self._event_listeners: dict[str, list[EventListener]] = {}

    # ════════════════════════════════════════════════════════════
    # 注册接口
    # ════════════════════════════════════════════════════════════

    def register_command(self, internal: str, handler: CmdHandler,
                         global_check: bool = False) -> None:
        """
        注册指令处理器。
        - internal:      内部命令名（"help", "punish_do" 等）
        - handler:       异步处理函数
                         (level, sender_id, group_id, parts, at_list, sender_card)
                         -> Optional[str]
        - global_check:  True=对所有配置检查权限（help/config 用）
        """
        self._commands[internal] = handler
        if global_check:
            self._global_commands_set.add(internal)

    def register_event(self, event_type: str, handler: EventListener) -> None:
        """
        注册事件监听器。
        - event_type: "notice.group_increase", "notice.group_decrease" 等
        - handler:    接收原始 event dict，无返回值
        """
        self._event_listeners.setdefault(event_type, []).append(handler)

    # ════════════════════════════════════════════════════════════
    # Bot 能力 API — 消息发送
    # ════════════════════════════════════════════════════════════

    async def send_message(self, group_id: int, text: str) -> bool:
        """发送群聊文本消息。空字符串直接返回 True。"""
        if not text:
            return True
        return await self._api.send_group_msg(group_id, text)

    async def send_image(self, group_id: int, png_bytes: bytes) -> bool:
        """发送图片消息（自动 base64 编码 + CQ 码封装）。"""
        import base64
        return await self.send_message(
            group_id,
            f"[CQ:image,file=base64://{base64.b64encode(png_bytes).decode()}]"
        )

    def _render_png(self, maker) -> Optional[bytes]:
        """调用渲染函数生成 PNG，自动处理 Pillow 缺失/异常并禁用渲染。"""
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

    # ════════════════════════════════════════════════════════════
    # Bot 能力 API — 管理操作
    # ════════════════════════════════════════════════════════════

    async def kick(self, group_id: int, user_id: int,
                   reject_add: bool = False) -> bool:
        """踢出群成员。reject_add=True 时加入黑名单拒绝再次申请。"""
        return await self._api.set_group_kick(group_id, user_id, reject_add)

    async def ban(self, group_id: int, user_id: int,
                  duration_sec: int) -> bool:
        """禁言群成员（秒）。"""
        return await self._api.set_group_ban(group_id, user_id, duration_sec)

    async def unban(self, group_id: int, user_id: int) -> bool:
        """解除禁言。"""
        return await self._api.set_group_ban(group_id, user_id, 0)

    # ════════════════════════════════════════════════════════════
    # Bot 能力 API — 信息查询
    # ════════════════════════════════════════════════════════════

    async def get_member_list(self, group_id: int) -> list:
        """获取群成员列表。"""
        return await self._api.get_group_member_list(group_id)

    async def is_member_in_group(self, group_id: int, user_id: int) -> bool:
        """检查成员是否在群内。"""
        return await self._api.is_member_in_group(group_id, user_id)

    async def get_muted_members(self, group_id: int) -> list:
        """获取当前被禁言的成员列表。"""
        return await self._api.get_muted_members(group_id)

    # ════════════════════════════════════════════════════════════
    # 生命周期
    # ════════════════════════════════════════════════════════════

    def load(self):
        """加载所有配置和运行时数据"""
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
        """持久化所有配置"""
        for name, state in self.configs.items():
            self.dm.save_config(name, state)

    # ════════════════════════════════════════════════════════════
    # 权限计算
    # ════════════════════════════════════════════════════════════

    def _level(self, qq: str) -> int:
        """计算用户权限等级。0=超管，-1=无权限/路人，≥1=管理"""
        if qq in self.super_admins:
            return 0
        # 在权限系统中查找（返回任意配置里的最高权限）
        best = -1
        for cfg in self.configs.values():
            lv = cfg.permissions.get(qq, -1)
            if lv > best:
                best = lv
        return best

    # ════════════════════════════════════════════════════════════
    # 配置查找
    # ════════════════════════════════════════════════════════════

    def _find_configs(self, group_id: str) -> list[ConfigState]:
        """查找包含此群的所有配置"""
        result = []
        for cfg in self.configs.values():
            if (cfg.info.notify_group and cfg.info.notify_group == group_id) or \
               group_id in cfg.info.execution_groups:
                result.append(cfg)
        return result

    def _get_config(self, name: str) -> Optional[ConfigState]:
        """按名称获取配置"""
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

    # ════════════════════════════════════════════════════════════
    # 命令配置检查
    # ════════════════════════════════════════════════════════════

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

    def _get_cmd_item_with_sub(self, internal: str, configs: list[ConfigState]) -> Optional[CommandItem]:
        """获取有 sub 的命令配置（用于子命令检查；配置优先但跳过无 sub 的）"""
        for cfg in configs:
            item = cfg.commands.commands.get(internal)
            if item and item.enabled and item.sub is not None:
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
        # 超管全部通过；min_lv=-1 所有人可用
        if user_level == 0 or min_lv == -1:
            return True
        if user_level == -1:
            return False  # 普通成员，非 -1 命令不可用
        return user_level <= min_lv

    def _check_sub_command(self, internal: str, sub_name: str,
                           configs: list[ConfigState], user_level: int) -> bool:
        """检查子命令是否可用（遍历配置+全局，找有该子命令的）"""
        if not configs:
            return True

        # 先查各配置，再看全局；跳过没有目标子命令的 item
        for cfg in configs:
            item = cfg.commands.commands.get(internal)
            if item and item.enabled:
                sub = self._get_sub_item(item, sub_name)
                if sub and sub.enabled:
                    min_lv = self._resolve_min_level(sub, item)
                    if user_level == 0 or min_lv == -1:
                        return True
                    if user_level == -1:
                        return False
                    return user_level <= min_lv

        # 全局回退
        item = self.global_commands.commands.get(internal)
        if item and item.enabled:
            sub = self._get_sub_item(item, sub_name)
            if sub and sub.enabled:
                min_lv = self._resolve_min_level(sub, item)
                if user_level == 0 or min_lv == -1:
                    return True
                if user_level == -1:
                    return False
                return user_level <= min_lv

        return False

    # ════════════════════════════════════════════════════════════
    # 消息入口（分发器）
    # ════════════════════════════════════════════════════════════

    async def handle_message(self, event: dict) -> Optional[str]:
        """处理群消息事件，查注册表分发到对应 handler"""
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

        # 提取 at 列表
        at_list = self._extract_at(event)

        # 解析外部名 → 内部名
        internal = self._cmd_map.get(ext_cmd)
        if internal is None:
            return None

        # 查注册表
        handler = self._commands.get(internal)
        if handler is None:
            return None  # 未注册的命令，不响应

        # 命令启用 + 权限检查
        if internal in self._global_commands_set:
            ok = self._check_command(internal, list(self.configs.values()), level)
        else:
            match_cfgs = self._find_configs(group_id)
            ok = self._check_command(internal, match_cfgs, level)
        if not ok:
            return None

        # 提取发送者群名片
        sender = event.get("sender", {})
        sender_card = sender.get("card", "") or sender.get("nickname", "")

        # 分发到 handler
        return await handler(level, sender_id, group_id, parts, at_list, sender_card)

    # ════════════════════════════════════════════════════════════
    # 事件入口（分发器）
    # ════════════════════════════════════════════════════════════

    async def handle_notice(self, event: dict):
        """处理通知事件 → 分发给注册的事件监听器"""
        notice_type = event.get("notice_type", "")
        event_key = f"notice.{notice_type}"
        for listener in self._event_listeners.get(event_key, []):
            try:
                await listener(event)
            except Exception:
                logger.exception(f"事件监听器异常: {event_key}")

    # ════════════════════════════════════════════════════════════
    # 共享工具
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _extract_at(event: dict) -> List[str]:
        """从消息中提取 @QQ 列表"""
        ats = []
        raw = event.get("raw_message", event.get("message", ""))
        for m in re.finditer(r'\[CQ:at,qq=(\d+)\]', str(raw)):
            qq = m.group(1)
            if qq and qq != "0":
                ats.append(qq)
        return ats

    @staticmethod
    def _extract_qq(text: str) -> Optional[str]:
        """从文本中提取 QQ 号"""
        if not text:
            return None
        m = re.search(r'\d{5,}', text)
        return m.group() if m else None

    @staticmethod
    def _parse_duration(dur: str) -> Optional[int]:
        """解析时长：纯数字=天，组合 1d2h30m。返回秒。"""
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
        """解析目标 QQ：at 优先，否则从文本提取"""
        if at_list:
            return at_list[0]
        return self._extract_qq(text)

    async def _notify_admin(self, cfg: ConfigState, msg: str):
        """向配置的通知群发送消息"""
        ng = cfg.info.notify_group
        if ng:
            try:
                await self.send_message(int(ng), msg)
            except Exception as e:
                logger.error(f"通知通知群失败: {e}")

    # ════════════════════════════════════════════════════════════
    # 数据操作（供 punish/rp 模块调用）
    # ════════════════════════════════════════════════════════════

    def _add_record(self, cfg_name: str, sender: str, from_group: str, target: int,
                    method: str, content: str, reason: str, status: str) -> PunishRecord:
        """创建处罚记录"""
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
        """加入黑名单"""
        cfg = self.configs[cfg_name]
        for b in cfg.blacklist:
            if b.qq == qq and b.group_name == group_name:
                return
        cfg.blacklist.append(BlacklistItem(
            qq=qq, reason=reason, add_time=int(time.time()),
            group_name=group_name))

    def _blacklist_remove(self, cfg_name: str, qq: int, group_name: str):
        """移出黑名单"""
        cfg = self.configs[cfg_name]
        cfg.blacklist = [b for b in cfg.blacklist
                         if not (b.qq == qq and b.group_name == group_name)]
