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
from datetime import datetime
from pathlib import Path

from bot.api import OneBotAPI
from bot.client import OneBotWS
from bot.handler import EventHandler
from core.data_manager import DataManager
from core.dispatcher import CommandDispatcher
from features.basic.help import HelpModule
from features.basic.config_cmd import ConfigModule
from features.basic.admin import AdminModule
from features.punish.punish import PunishModule
from features.punish.rp import RpModule
from features.punish.history import HistoryModule

logger = logging.getLogger("Hollow")

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 最小控制台日志 — 确保首次运行（无 config.json）时也能看到输出
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
)


def setup_logging(log_cfg: dict):
    """根据配置重新设置日志：控制台 + 可选文件输出"""
    log_level = getattr(logging, log_cfg.get("log_level", "INFO").upper(), logging.INFO)
    log_to_file = log_cfg.get("log_to_file", True)
    log_dir = log_cfg.get("log_dir", "logs")

    root = logging.getLogger()

    # 清除 basicConfig 添加的默认 handler，按配置重建
    root.handlers.clear()
    root.setLevel(log_level)

    # 控制台 handler
    console = logging.StreamHandler()
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    root.addHandler(console)

    # 文件 handler
    if log_to_file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        log_file = log_path / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        root.addHandler(file_handler)
        logger.info(f"日志输出到文件: {log_file} (level={logging.getLevelName(log_level)})")

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
            "log": {
                "log_to_file": True,
                "log_level": "INFO",
                "log_dir": "logs",
            },
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
    log_cfg = cfg.get("log", {})

    # 按配置重建日志（覆盖 basicConfig 的默认行为）
    setup_logging(log_cfg)

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

    # ---- 指令分发 ----
    dispatcher = CommandDispatcher(
        api=api, dm=dm,
        wake_words=pl.get("wake_words", ["/", "!", "。"]),
        super_admins={str(a) for a in pl.get("super_admins", [])},
        render_enabled=render_cfg.get("enabled", True),
    )
    dispatcher.load()
    if not dispatcher.super_admins:
        logger.warning("⚠ 未配置 super_admins，请在 config.json 中设置！")

    # ---- 功能模块注册 ----
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

    # ---- 事件 ----
    handler = EventHandler(api, dispatcher)
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
        dispatcher.save()
        logger.info("数据已保存，退出。")


if __name__ == "__main__":
    asyncio.run(main())
