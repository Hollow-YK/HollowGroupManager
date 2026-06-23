#!/usr/bin/env python3
"""
HollowGroupManager - 多群联动管理 Bot
基于 OneBot v11 标准协议，纯 Python 实现。

通信模式 (config.json → onebot.mode):
  "ws"             — 正向 WS Universal（单连接，API+事件共线）
  "http_ws"        — HTTP API + 正向 WS 事件（默认，最常用）
  "ws_reverse"     — 反向 WS Universal（Bot 监听，OneBot 连过来）
  "http_ws_reverse"— HTTP API + 反向 WS 事件

Copyright (C) 2026  Hollow-YK  |  License: GNU AGPL v3
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from bot.api import OneBotAPI
from bot.client import OneBotWS
from bot.handler import EventHandler
from core.data_manager import DataManager
from core.commands import CommandHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Hollow")

MODES = ("ws", "http_ws", "ws_reverse", "http_ws_reverse")


def load_config(path: str = "config.json") -> dict:
    p = Path(path)
    if not p.exists():
        default = {
            "onebot": {
                "mode": "http_ws",
                "http_url": "http://127.0.0.1:3000",
                "ws_url": "ws://127.0.0.1:3001",
                "ws_reverse_port": 8080,
                "access_token": "",
            },
            "plugin": {
                "wake_words": ["/", "!", "。"],
                "super_admins": [],
                "data_dir": "data",
            },
            "render": {"enabled": True},
        }
        p.write_text(json.dumps(default, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        logger.info(f"已生成默认配置: {path}，请修改后重启。")
        sys.exit(0)
    return json.loads(p.read_text(encoding="utf-8"))


async def main():
    logger.info("HollowGroupManager 启动中...")

    cfg = load_config()
    ob = cfg.get("onebot", {})
    pl = cfg.get("plugin", {})
    render_cfg = cfg.get("render", {})

    mode = ob.get("mode", "http_ws")
    if mode not in MODES:
        logger.error(f"未知模式: {mode}，可选: {', '.join(MODES)}")
        sys.exit(1)

    token = ob.get("access_token", "")
    http_url = ob.get("http_url", "")
    ws_url = ob.get("ws_url", "")
    ws_reverse_port = int(ob.get("ws_reverse_port", 0))

    # ---- API ----
    use_http = mode in ("http_ws", "http_ws_reverse")
    api = OneBotAPI(http_url=http_url if use_http else "", access_token=token)

    # ---- WS ----
    ws = OneBotWS(access_token=token)

    # WS Universal 模式：API 走 WS 发送，响应也走 WS 回收
    if mode in ("ws", "ws_reverse"):
        api.set_ws_send(ws.send)
        ws.on_api_response(api.handle_ws_response)

    # ---- 数据 ----
    dm = DataManager(pl.get("data_dir", "data"))
    dm.check_all()

    # ---- 指令 ----
    cmd = CommandHandler(
        api=api, dm=dm,
        wake_words=pl.get("wake_words", ["/", "!", "。"]),
        super_admins={str(a) for a in pl.get("super_admins", [])},
        render_enabled=render_cfg.get("enabled", True),
    )
    cmd.load()
    if not cmd.super_admins:
        logger.warning("⚠ 未配置 super_admins，请在 config.json 中设置！")

    # ---- 事件 ----
    handler = EventHandler(api, cmd)
    ws.on_event("message", handler.on_message)
    ws.on_event("notice", handler.on_notice)
    ws.on_event("request", handler.on_request)

    # ---- 启动 ----
    tasks = []
    if mode in ("http_ws", "ws"):
        tasks.append(asyncio.create_task(ws.connect(ws_url)))
    if mode in ("ws_reverse", "http_ws_reverse"):
        tasks.append(asyncio.create_task(ws.serve("0.0.0.0", ws_reverse_port)))

    logger.info(f"HollowGroupManager 已就绪 (mode={mode})")

    try:
        await asyncio.gather(*tasks) if tasks else await asyncio.Future()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    finally:
        await ws.stop()
        cmd.save()
        logger.info("数据已保存，退出。")


if __name__ == "__main__":
    asyncio.run(main())
