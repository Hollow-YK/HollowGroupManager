"""
调试核心引擎 — 通过模拟 OneBot 事件注入来测试业务逻辑。

提供:
  - DebugAPI:      与 OneBotAPI 签名一致的模拟 API，记录所有调用
  - DebugManager:   构建完整测试管线的事件注入器
  - DebugResult:    注入结果（回复 + API 调用记录 + 异常）
  - APICall:        单次 API 调用记录

使用方式:
    manager = DebugManager.from_config(cfg, data_dir="data/test")
    result = await manager.inject_event({
        "post_type": "message",
        "message_type": "group",
        "group_id": 123456,
        "user_id": 789012,
        "raw_message": "ghelp",
    })
    print(result.reply, result.api_calls)

Copyright (C) 2026  Hollow-YK  |  License: GNU AGPL v3
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Callable, Awaitable

from bot.handler import EventHandler
from core.data_manager import DataManager
from core.dispatcher import CommandDispatcher

# 功能模块
from features.basic.help import HelpModule
from features.basic.config_cmd import ConfigModule
from features.basic.admin import AdminModule
from features.punish.punish import PunishModule
from features.punish.rp import RpModule
from features.punish.history import HistoryModule
from features.verify.approval import ApprovalModule
from features.verify.verification import VerificationModule

logger = logging.getLogger("Hollow.Debug")


# ════════════════════════════════════════════════════════════════
# 数据类
# ════════════════════════════════════════════════════════════════

@dataclass
class APICall:
    """单次 API 调用记录"""
    action: str
    params: dict
    result: Any = None
    timestamp: float = field(default_factory=time.time)


@dataclass
class DebugResult:
    """事件注入结果"""
    reply: Optional[str] = None          # 消息回复文本（仅消息事件有）
    api_calls: list[APICall] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_ms: float = 0


# ════════════════════════════════════════════════════════════════
# 模拟 API
# ════════════════════════════════════════════════════════════════

class DebugAPI:
    """与 OneBotAPI 签名一致的模拟 API。
    所有方法记录调用参数并返回模拟成功结果，不发起真实网络请求。"""

    def __init__(self):
        self.calls: list[APICall] = []
        # 模拟群成员: group_id(int) → list[{user_id, nickname, card, ...}]
        self._members: dict[int, list[dict]] = {}
        # 模拟禁言成员: group_id(int) → list[{user_id, nickname, duration}]
        self._muted: dict[int, list[dict]] = {}

    def _record(self, action: str, params: dict, result: Any = True) -> Any:
        call = APICall(action=action, params=dict(params))
        call.result = result
        self.calls.append(call)
        return result

    def clear(self):
        """清空调用记录（保留成员数据）"""
        self.calls.clear()

    # ── 成员数据预设 ──

    def set_mock_members(self, group_id: int, members: list[dict]):
        """预置群成员列表。
        members: [{"user_id": 111, "nickname": "test", "card": "别名"}, ...]
        """
        self._members[group_id] = members

    def set_mock_muted(self, group_id: int, muted: list[dict]):
        """预置禁言成员。
        muted: [{"user_id": 111, "nickname": "test", "duration": 600}, ...]
        """
        self._muted[group_id] = muted

    # ── 消息发送 ──

    async def send_group_msg(self, group_id: int, message) -> Optional[int]:
        """发送群聊消息。message 为 str 或 list[dict]."""
        msg_repr = message if isinstance(message, str) else f"[{len(message)} segments]"
        self._record("send_group_msg", {"group_id": group_id, "message": msg_repr},
                     {"message_id": 100000 + len(self.calls)})
        return 100000 + len(self.calls)

    # ── 群成员管理 ──

    async def set_group_kick(self, group_id: int, user_id: int,
                             reject_add_request: bool = False) -> bool:
        return self._record("set_group_kick",
                            {"group_id": group_id, "user_id": user_id,
                             "reject_add_request": reject_add_request})

    async def set_group_ban(self, group_id: int, user_id: int,
                            duration: int) -> bool:
        return self._record("set_group_ban",
                            {"group_id": group_id, "user_id": user_id,
                             "duration": duration})

    async def get_group_member_list(self, group_id: int) -> Optional[list[dict]]:
        members = self._members.get(group_id, [])
        self._record("get_group_member_list", {"group_id": group_id}, members)
        return members

    async def is_member_in_group(self, group_id: int, user_id: int) -> bool:
        members = self._members.get(group_id, [])
        result = any(m.get("user_id") == user_id for m in members)
        self._record("is_member_in_group",
                     {"group_id": group_id, "user_id": user_id}, result)
        return result

    async def get_muted_members(self, group_id: int) -> list[dict]:
        muted = self._muted.get(group_id, [])
        self._record("get_muted_members", {"group_id": group_id}, muted)
        return muted

    async def get_login_info(self) -> Optional[dict]:
        """获取机器人自身信息（模拟）。"""
        info = {"user_id": 10000, "nickname": "DebugBot"}
        self._record("get_login_info", {}, info)
        return info

    # ── 请求处理 ──

    async def set_group_add_request(self, flag: str, sub_type: str,
                                     approve: bool, reason: str = "") -> bool:
        return self._record("set_group_add_request",
                            {"flag": flag, "sub_type": sub_type,
                             "approve": approve, "reason": reason})


# ════════════════════════════════════════════════════════════════
# 调试管理器
# ════════════════════════════════════════════════════════════════

class DebugManager:
    """构建完整测试管线，通过模拟事件注入测试业务逻辑。

    用法:
        cfg = json.loads(Path("config.json").read_text("utf-8"))
        manager = DebugManager.from_config(cfg, data_dir="data/test")
        result = await manager.inject_event({...})
    """

    def __init__(self, api: DebugAPI, dispatcher: CommandDispatcher,
                 handler: EventHandler):
        self.api = api
        self.dispatcher = dispatcher
        self.handler = handler

    @classmethod
    def from_config(cls, cfg: dict, data_dir: str = "data/test") -> "DebugManager":
        """根据配置字典构建完整的调试管线。

        自动完成: DataManager → CommandDispatcher → 模块注册 → EventHandler
        """
        pl = cfg.get("plugin", {})
        render_cfg = cfg.get("render", {})

        api = DebugAPI()

        # 数据管理器
        dm = DataManager(pl.get("data_dir", data_dir))

        # 指令分发器
        wake_words = pl.get("wake_words", ["/", "!", "。"])
        super_admins = {str(a) for a in pl.get("super_admins", [])}
        dispatcher = CommandDispatcher(
            api=api, dm=dm,  # type: ignore[arg-type]  # DebugAPI 与 OneBotAPI 接口兼容
            wake_words=wake_words,
            super_admins=super_admins,
            render_enabled=render_cfg.get("enabled", False),  # 调试默认关闭渲染
        )
        dispatcher.load()

        # ── 注册功能模块（与 main.py 一致）──
        punish_mod = PunishModule(dispatcher)
        dispatcher.register_command("help",
            HelpModule(dispatcher).handle, global_check=True)
        dispatcher.register_command("config",
            ConfigModule(dispatcher).handle, global_check=True)
        dispatcher.register_command("admin",
            AdminModule(dispatcher).handle)
        dispatcher.register_command("punish_do",
            punish_mod.handle)
        dispatcher.register_command("punish_revoke",
            RpModule(dispatcher).handle)
        dispatcher.register_command("punish_history",
            HistoryModule(dispatcher).handle)
        dispatcher.register_event("notice.group_increase",
            punish_mod.on_member_join)

        approval_mod = ApprovalModule(dispatcher)
        verify_mod = VerificationModule(dispatcher, approval_mod)

        dispatcher.register_command("approval", approval_mod.handle)
        dispatcher.register_event("request.group_add", approval_mod.on_request_group_add)
        dispatcher.register_event("notice.group_increase", approval_mod.on_member_increase)

        dispatcher.register_command("verify", verify_mod.handle)
        dispatcher.register_event("notice.group_increase", verify_mod.on_member_increase)
        dispatcher.register_event("message.group", verify_mod.on_raw_message)

        # 事件处理器
        handler = EventHandler(api, dispatcher)  # type: ignore[arg-type]

        return cls(api=api, dispatcher=dispatcher, handler=handler)

    # ── 超管覆盖 ──

    def set_super_admins(self, admins: set[str]):
        """临时覆盖超管列表（方便测试管理命令）"""
        self.dispatcher.super_admins = admins

    # ── 事件注入 ──

    async def inject_event(self, event: dict) -> DebugResult:
        """注入模拟 OneBot 事件，捕获回复和 API 调用。

        event 格式参考 OneBot v11 事件标准:
          - 消息: {"post_type": "message", "message_type": "group", ...}
          - 通知: {"post_type": "notice", "notice_type": "...", ...}
          - 请求: {"post_type": "request", "request_type": "...", ...}
        """
        self.api.clear()
        result = DebugResult()
        t0 = time.perf_counter()

        try:
            pt = event.get("post_type", "")

            if pt == "message":
                # 消息事件走 EventHandler.on_message（内部调用 cmd.handle_message +
                # api.send_group_msg，reply 被 DebugAPI 拦截）
                await self.handler.on_message(event)
                # 从 API 调用记录中提取 send_group_msg 的 message 内容作为 reply
                for call in self.api.calls:
                    if call.action == "send_group_msg":
                        msg = call.params.get("message", "")
                        result.reply = msg if isinstance(msg, str) else (
                            f"[{len(msg)} segments]" if isinstance(msg, list) else str(msg))
                        break

            elif pt == "notice":
                await self.handler.on_notice(event)

            elif pt == "request":
                await self.handler.on_request(event)

            elif "meta_event_type" in event:
                # meta_event 不需要处理
                pass
            else:
                result.error = f"未知事件类型: post_type={pt!r}"

        except Exception as e:
            logger.exception(f"事件注入异常: {e}")
            result.error = f"{type(e).__name__}: {e}"

        result.api_calls = list(self.api.calls)
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        return result

    # ── 便捷方法 ──

    async def inject_message(self, group_id: int, user_id: int,
                              raw_message: str, *,
                              sender_card: str = "",
                              at_list: list[str] | None = None,
                              message_id: int = 1) -> DebugResult:
        """便捷方法：构造并注入一条群消息事件。"""
        message = raw_message
        if at_list:
            for qq in at_list:
                message = f"[CQ:at,qq={qq}] " + message

        event = {
            "post_type": "message",
            "message_type": "group",
            "sub_type": "normal",
            "message_id": message_id,
            "group_id": group_id,
            "user_id": user_id,
            "raw_message": raw_message,
            "message": message,
            "sender": {
                "user_id": user_id,
                "nickname": f"user_{user_id}",
                "card": sender_card or "",
            },
        }
        return await self.inject_event(event)

    async def inject_notice(self, notice_type: str, group_id: int,
                             user_id: int, **extra) -> DebugResult:
        """便捷方法：构造并注入一条通知事件。"""
        event = {
            "post_type": "notice",
            "notice_type": notice_type,
            "group_id": group_id,
            "user_id": user_id,
            **extra,
        }
        return await self.inject_event(event)

    async def inject_request(self, request_type: str, sub_type: str,
                              group_id: int, user_id: int,
                              **extra) -> DebugResult:
        """便捷方法：构造并注入一条请求事件。"""
        event = {
            "post_type": "request",
            "request_type": request_type,
            "sub_type": sub_type,
            "group_id": group_id,
            "user_id": user_id,
            **extra,
        }
        return await self.inject_event(event)
