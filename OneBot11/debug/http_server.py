"""
HTTP 调试端点 — 提供 REST API 进行模拟事件注入。

端点:
  POST /debug/event    注入 OneBot 事件，返回 DebugResult JSON
  POST /debug/members  预置群成员列表
  POST /debug/run      运行 JSON 测试文件
  GET  /debug/health   健康检查

Copyright (C) 2026  Hollow-YK  |  License: GNU AGPL v3
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from aiohttp import web

from core.data_manager import DataManager
from core.dispatcher import CommandDispatcher
from debug import DebugManager, DebugResult

logger = logging.getLogger("Hollow.Debug.HTTP")


def _result_to_dict(result: DebugResult) -> dict:
    """将 DebugResult 转为 JSON 可序列化字典"""
    return {
        "reply": result.reply,
        "api_calls": [
            {
                "action": c.action,
                "params": {k: str(v) if not isinstance(v, (int, float, bool, type(None), str, list, dict)) else v
                           for k, v in c.params.items()},
            }
            for c in result.api_calls
        ],
        "error": result.error,
        "elapsed_ms": round(result.elapsed_ms, 1),
    }


class DebugHTTPHandler:
    """aiohttp HTTP 请求处理器"""

    def __init__(self, manager: DebugManager):
        self.manager = manager

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "mode": "debug"})

    async def inject_event(self, request: web.Request) -> web.Response:
        """POST /debug/event — 注入 OneBot 事件"""
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            return web.json_response(
                {"error": f"Invalid JSON: {e}"}, status=400)

        if not isinstance(body, dict):
            return web.json_response(
                {"error": "body must be a JSON object"}, status=400)

        result = await self.manager.inject_event(body)
        return web.json_response(_result_to_dict(result))

    async def inject_message(self, request: web.Request) -> web.Response:
        """POST /debug/message — 便捷消息注入"""
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            return web.json_response(
                {"error": f"Invalid JSON: {e}"}, status=400)

        group_id = body.get("group_id")
        user_id = body.get("user_id")
        raw_message = body.get("raw_message", body.get("text", ""))

        if not group_id or not user_id:
            return web.json_response(
                {"error": "group_id and user_id are required"}, status=400)

        result = await self.manager.inject_message(
            group_id=int(group_id),
            user_id=int(user_id),
            raw_message=str(raw_message),
            sender_card=str(body.get("sender_card", "")),
            at_list=body.get("at_list"),
        )
        return web.json_response(_result_to_dict(result))

    async def set_members(self, request: web.Request) -> web.Response:
        """POST /debug/members — 预置群成员"""
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            return web.json_response(
                {"error": f"Invalid JSON: {e}"}, status=400)

        group_id = body.get("group_id")
        members = body.get("members", [])

        if not group_id:
            return web.json_response(
                {"error": "group_id is required"}, status=400)

        if not isinstance(members, list):
            return web.json_response(
                {"error": "members must be a list"}, status=400)

        self.manager.api.set_mock_members(int(group_id), members)

        muted = body.get("muted", [])
        if muted:
            self.manager.api.set_mock_muted(int(group_id), muted)

        return web.json_response({
            "status": "ok",
            "group_id": group_id,
            "member_count": len(members),
            "muted_count": len(muted),
        })

    async def run_tests(self, request: web.Request) -> web.Response:
        """POST /debug/run — 运行测试文件"""
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            return web.json_response(
                {"error": f"Invalid JSON: {e}"}, status=400)

        file_path = body.get("file")
        if not file_path:
            return web.json_response(
                {"error": "file path is required"}, status=400)

        from debug.runner import run_test_file
        path = Path(file_path)
        if not path.exists():
            return web.json_response(
                {"error": f"File not found: {file_path}"}, status=404)

        report = await run_test_file(str(path), self.manager)
        return web.json_response(report.to_dict())

    def register(self, app: web.Application):
        app.router.add_get("/debug/health", self.health)
        app.router.add_post("/debug/event", self.inject_event)
        app.router.add_post("/debug/message", self.inject_message)
        app.router.add_post("/debug/members", self.set_members)
        app.router.add_post("/debug/run", self.run_tests)


async def start_http_server(port: int, dispatcher: CommandDispatcher,
                            dm: DataManager, cfg: dict):
    """启动 HTTP 调试服务器（后台任务）。"""
    manager = DebugManager.from_config(cfg)
    handler = DebugHTTPHandler(manager)

    app = web.Application()
    handler.register(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)

    try:
        await site.start()
        logger.info(f"[Debug HTTP] 监听 http://127.0.0.1:{port}")
        # 保持运行直到被取消
        await asyncio.Future()
    except asyncio.CancelledError:
        logger.info("[Debug HTTP] 正在关闭...")
    finally:
        await runner.cleanup()
