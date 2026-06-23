"""
OneBot v11 API 封装 — 支持 HTTP 和 WebSocket 两种传输。

HTTP 模式: POST http://host:port/{action}
WS 模式:   通过 WebSocket 发送 {"action":..., "params":...}

参考: https://github.com/botuniverse/onebot-11/blob/master/api/public.md
"""
import asyncio
import json
import logging
from typing import Optional, Any, Callable, Awaitable

import aiohttp

logger = logging.getLogger("Hollow.API")

# WS 发送回调: (json_str) -> None
WSSend = Callable[[str], Awaitable[None]]


class OneBotAPI:
    """OneBot v11 API 调用 — HTTP + 可选 WS"""

    def __init__(self, http_url: str = "", access_token: str = ""):
        self.http_url = http_url.rstrip("/") if http_url else ""
        self.access_token = access_token
        self._ws_send: Optional[WSSend] = None
        self._ws_responses: dict[str, asyncio.Future] = {}
        self._echo_counter = 0

    def set_ws_send(self, send: WSSend):
        """注入 WS 发送通道。设置后，无 HTTP 时 API 走 WS。"""
        self._ws_send = send

    @property
    def use_ws(self) -> bool:
        return self._ws_send is not None

    # ==================== 传输层 ====================

    async def _call(self, action: str, params: dict) -> Optional[Any]:
        """调用 OneBot action，优先 HTTP，无 HTTP 则走 WS"""
        if self.http_url:
            return await self._call_http(action, params)
        if self._ws_send:
            return await self._call_ws(action, params)
        logger.error(f"[API] 无可用传输 (http_url 和 ws 均未配置)")
        return None

    async def _call_http(self, action: str, params: dict) -> Optional[Any]:
        url = f"{self.http_url}/{action}"
        payload = {"action": action, "params": params}
        headers = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        logger.error(f"[API] {action} HTTP {resp.status}")
                        return None
                    result = await resp.json()
                    if result.get("status") == "ok":
                        return result.get("data")
                    elif result.get("status") == "async":
                        logger.info(f"[API] {action} 异步调用已接受")
                        return True
                    else:
                        logger.warning(f"[API] {action} 失败: {result}")
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"[API] {action} 网络错误: {e}")
            return None
        except Exception as e:
            logger.error(f"[API] {action} 未知错误: {e}")
            return None

    async def _call_ws(self, action: str, params: dict) -> Optional[Any]:
        if not self._ws_send:
            return None
        self._echo_counter += 1
        echo = str(self._echo_counter)
        payload = {"action": action, "params": params, "echo": echo}

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._ws_responses[echo] = future

        try:
            await self._ws_send(json.dumps(payload, ensure_ascii=False))
            result = await asyncio.wait_for(future, timeout=10)
            if result.get("status") == "ok":
                return result.get("data")
            else:
                logger.warning(f"[API-WS] {action} 失败: {result}")
                return None
        except asyncio.TimeoutError:
            logger.error(f"[API-WS] {action} 超时")
            return None
        finally:
            self._ws_responses.pop(echo, None)

    def handle_ws_response(self, msg: dict):
        """处理 WS 上的 API 响应"""
        echo = msg.get("echo")
        if echo and echo in self._ws_responses:
            future = self._ws_responses.pop(echo, None)
            if future and not future.done():
                future.set_result(msg)

    # ==================== 消息发送 ====================

    async def send_group_msg(self, group_id: int, message: str) -> Optional[int]:
        data = await self._call("send_group_msg", {
            "group_id": group_id, "message": message,
        })
        return data.get("message_id") if isinstance(data, dict) else None

    # ==================== 群成员管理 ====================

    async def get_group_member_list(self, group_id: int) -> Optional[list[dict]]:
        data = await self._call("get_group_member_list", {"group_id": group_id})
        return data if isinstance(data, list) else None

    async def set_group_kick(self, group_id: int, user_id: int,
                             reject_add_request: bool = False) -> bool:
        data = await self._call("set_group_kick", {
            "group_id": group_id, "user_id": user_id,
            "reject_add_request": reject_add_request,
        })
        return data is not None

    async def set_group_ban(self, group_id: int, user_id: int,
                            duration: int) -> bool:
        data = await self._call("set_group_ban", {
            "group_id": group_id, "user_id": user_id, "duration": duration,
        })
        return data is not None

    # ==================== 辅助 ====================

    async def is_member_in_group(self, group_id: int, user_id: int) -> bool:
        members = await self.get_group_member_list(group_id)
        if members is None:
            return False
        for m in members:
            if m.get("user_id") == user_id:
                return True
        return False

    async def get_muted_members(self, group_id: int) -> list[dict]:
        """获取被禁言成员（通过 get_group_member_list 推断）"""
        members = await self.get_group_member_list(group_id)
        if members is None:
            return []
        import time
        now = int(time.time())
        return [
            {"user_id": m.get("user_id", 0),
             "nickname": m.get("nickname", "") or m.get("card", ""),
             "duration": m.get("shut_up_timestamp", 0) - now}
            for m in members
            if m.get("shut_up_timestamp", 0) > now
        ]
