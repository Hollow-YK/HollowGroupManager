"""
事件处理器：将 OneBot v11 事件分发到 CommandHandler
"""
import logging

from bot.api import OneBotAPI
from core.dispatcher import CommandDispatcher

logger = logging.getLogger("Hollow.Handler")


class EventHandler:
    """OneBot v11 事件 → 业务逻辑的桥梁

    消息回复统一经 `CommandDispatcher.send_message` 出口（消息段数组），
    不直接调用 `api.send_group_msg`。
    """

    def __init__(self, api: OneBotAPI, cmd: CommandDispatcher):
        self.api = api
        self.cmd = cmd

    async def on_message(self, event: dict):
        """处理消息事件（回复经 `send_message` 以 text 段下发，CQ 安全）"""
        try:
            reply = await self.cmd.handle_message(event)
            if reply:
                group_id = event.get("group_id")
                if group_id:
                    await self.cmd.send_message(int(group_id), reply)
        except Exception:
            logger.exception("消息处理异常")

    async def on_notice(self, event: dict):
        """处理通知事件"""
        try:
            await self.cmd.handle_notice(event)
        except Exception:
            logger.exception("通知处理异常")

    async def on_request(self, event: dict):
        """处理请求事件（加群邀请等）"""
        try:
            await self.cmd.handle_request(event)
        except Exception:
            logger.exception("请求处理异常")
