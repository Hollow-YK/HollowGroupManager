"""
事件处理器：将 OneBot v11 事件分发到 CommandHandler
"""
import logging
from typing import Optional

from bot.api import OneBotAPI
from core.commands import CommandHandler

logger = logging.getLogger("Hollow.Handler")


class EventHandler:
    """OneBot v11 事件 → 业务逻辑的桥梁"""

    def __init__(self, api: OneBotAPI, cmd: CommandHandler):
        self.api = api
        self.cmd = cmd

    async def on_message(self, event: dict):
        """处理消息事件"""
        try:
            reply = await self.cmd.handle_message(event)
            if reply:
                group_id = event.get("group_id")
                if group_id:
                    await self.api.send_group_msg(int(group_id), reply)
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
        # 暂不处理，可扩展
        pass
