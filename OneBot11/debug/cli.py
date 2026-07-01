"""
CLI 交互式调试 REPL — 在终端中模拟 OneBot 事件注入。

命令:
  msg     group=<id> user=<id> text="<raw>" [at=<qq>,...] [card=<name>]
  notice  <type> group=<id> user=<id> [extra...]
  request <type> <sub> group=<id> user=<id> [extra...]
  members group=<id> set <user>:<nick> [<user>:<nick> ...]
  run     <test_file.json>
  help    显示帮助
  quit    退出

Copyright (C) 2026  Hollow-YK  |  License: GNU AGPL v3
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from pathlib import Path
from typing import Optional

from core.data_manager import DataManager
from core.dispatcher import CommandDispatcher
from debug import DebugManager, DebugResult

logger = logging.getLogger("Hollow.Debug.CLI")

PROMPT = "\033[36mdebug>\033[0m "
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
RESET = "\033[0m"

HELP_TEXT = f"""
{BOLD}{CYAN}HollowGroupManager 调试 CLI{RESET}

{CYAN}消息模拟:{RESET}
  {BOLD}msg{RESET} group={BOLD}<群号>{RESET} user={BOLD}<QQ>{RESET} text="<原始消息>" [at=<QQ>,...] [card=<名片>]
  示例: msg group=123456 user=789012 text="ghelp"
        msg group=123456 user=789012 text="gp kick" at=111222

{CYAN}通知模拟:{RESET}
  {BOLD}notice{RESET} <notice_type> group={BOLD}<群号>{RESET} user={BOLD}<QQ>{RESET} [key=value ...]
  示例: notice group_increase group=123456 user=789012

{CYAN}请求模拟:{RESET}
  {BOLD}request{RESET} <request_type> <sub_type> group={BOLD}<群号>{RESET} user={BOLD}<QQ>{RESET} [key=value ...]
  示例: request group add group=123456 user=789012 comment="答题"

{CYAN}成员预设:{RESET}
  {BOLD}members{RESET} group={BOLD}<群号>{RESET} set {BOLD}<QQ>:<昵称>{RESET} [<QQ>:<昵称> ...]
  示例: members group=123456 set 111:Alice 222:Bob

{CYAN}批量测试:{RESET}
  {BOLD}run{RESET} <test_file.json>

{CYAN}其他:{RESET}
  {BOLD}help{RESET}    显示此帮助  {BOLD}history{RESET} 查看最近事件
  {BOLD}clear{RESET}   清屏         {BOLD}quit{RESET}    退出
"""


def _parse_kv(args: list[str]) -> dict:
    """解析 key=value 和 key=val1,val2 参数"""
    result = {}
    for arg in args:
        if "=" not in arg:
            continue
        key, val = arg.split("=", 1)
        # 支持逗号分隔列表
        if "," in val:
            result[key] = [v.strip() for v in val.split(",")]
        else:
            # 尝试解析为数字
            try:
                result[key] = int(val)
            except ValueError:
                result[key] = val
    return result


def _format_result(result: DebugResult) -> str:
    """格式化 DebugResult 为可读文本"""
    lines = []

    # 耗时
    lines.append(f"{CYAN}⏱  耗时: {result.elapsed_ms:.1f}ms{RESET}")

    # 错误
    if result.error:
        lines.append(f"{RED}✗ 错误: {result.error}{RESET}")
        return "\n".join(lines)

    # 回复
    if result.reply:
        reply_text = result.reply[:500] + ("..." if len(result.reply) > 500 else "")
        lines.append(f"{GREEN}📤 回复:{RESET}")
        for line in reply_text.split("\n"):
            lines.append(f"   {line}")
    elif result.api_calls:
        lines.append(f"{YELLOW}📤 (已通过 API 发送，无文本回复){RESET}")
    else:
        lines.append(f"{YELLOW}📤 (无回复){RESET}")

    # API 调用
    if result.api_calls:
        lines.append(f"{MAGENTA}🔧 API 调用 ({len(result.api_calls)}):{RESET}")
        for i, call in enumerate(result.api_calls, 1):
            params_summary = ", ".join(
                f"{k}={v}" for k, v in call.params.items()
            )
            if len(params_summary) > 80:
                params_summary = params_summary[:77] + "..."
            lines.append(f"   {i}. {BOLD}{call.action}{RESET}({params_summary})")
    else:
        lines.append(f"{MAGENTA}🔧 API 调用: 无{RESET}")

    return "\n".join(lines)


class CLISession:
    """CLI 交互会话"""

    def __init__(self, manager: DebugManager):
        self.manager = manager
        self.history: list[tuple[str, DebugResult]] = []

    async def handle(self, line: str) -> Optional[str]:
        """处理一行输入，返回输出文本或 None 表示退出"""
        line = line.strip()
        if not line:
            return ""

        self.history.append((line, None))  # 占位，后续更新

        try:
            parts = shlex.split(line)
        except ValueError as e:
            return f"{RED}解析错误: {e}{RESET}"

        if not parts:
            return ""

        cmd = parts[0].lower()
        args = parts[1:]

        if cmd == "quit" or cmd == "exit" or cmd == "q":
            return None

        if cmd == "help" or cmd == "h":
            return HELP_TEXT

        if cmd == "clear" or cmd == "cls":
            print("\033[2J\033[H", end="")
            return ""

        if cmd == "history":
            return self._show_history()

        if cmd == "msg" or cmd == "message":
            return await self._cmd_msg(args)

        if cmd == "notice":
            return await self._cmd_notice(args)

        if cmd == "request":
            return await self._cmd_request(args)

        if cmd == "members":
            return await self._cmd_members(args)

        if cmd == "run":
            return await self._cmd_run(args)

        return f"{RED}未知命令: {cmd}，输入 help 查看帮助{RESET}"

    async def _cmd_msg(self, args: list[str]) -> str:
        kv = _parse_kv(args)

        group_id = kv.get("group")
        user_id = kv.get("user")
        text = kv.get("text", "")

        if not group_id or not user_id:
            return f"{RED}用法: msg group=<群号> user=<QQ> text=\"<消息>\" [at=<QQ>,...]{RESET}"

        at_list = kv.get("at", [])
        if isinstance(at_list, (int, str)):
            at_list = [str(at_list)]

        result = await self.manager.inject_message(
            group_id=int(group_id),
            user_id=int(user_id),
            raw_message=str(text),
            sender_card=str(kv.get("card", "")),
            at_list=at_list,
        )
        self.history[-1] = (f"msg group={group_id} user={user_id} text={text!r}", result)
        return _format_result(result)

    async def _cmd_notice(self, args: list[str]) -> str:
        if not args:
            return f"{RED}用法: notice <type> group=<群号> user=<QQ>{RESET}"

        notice_type = args[0]
        kv = _parse_kv(args[1:])
        group_id = kv.pop("group", None)
        user_id = kv.pop("user", None)

        if not group_id or not user_id:
            return f"{RED}用法: notice {notice_type} group=<群号> user=<QQ>{RESET}"

        result = await self.manager.inject_notice(
            notice_type=notice_type,
            group_id=int(group_id),
            user_id=int(user_id),
            **kv,
        )
        self.history[-1] = (f"notice {notice_type} group={group_id} user={user_id}", result)
        return _format_result(result)

    async def _cmd_request(self, args: list[str]) -> str:
        if len(args) < 2:
            return f"{RED}用法: request <type> <sub_type> group=<群号> user=<QQ>{RESET}"

        request_type = args[0]
        sub_type = args[1]
        kv = _parse_kv(args[2:])
        group_id = kv.pop("group", None)
        user_id = kv.pop("user", None)

        if not group_id or not user_id:
            return f"{RED}用法: request {request_type} {sub_type} group=<群号> user=<QQ>{RESET}"

        result = await self.manager.inject_request(
            request_type=request_type,
            sub_type=sub_type,
            group_id=int(group_id),
            user_id=int(user_id),
            **kv,
        )
        self.history[-1] = (
            f"request {request_type}/{sub_type} group={group_id} user={user_id}", result)
        return _format_result(result)

    async def _cmd_members(self, args: list[str]) -> str:
        if len(args) < 2 or args[1].lower() != "set":
            return f"{RED}用法: members group=<群号> set <QQ>:<昵称> ...{RESET}"

        kv = _parse_kv([args[0]])
        group_id = kv.get("group")
        if not group_id:
            return f"{RED}用法: members group=<群号> set <QQ>:<昵称> ...{RESET}"

        members = []
        for item in args[2:]:
            if ":" in item:
                uid, nick = item.split(":", 1)
                members.append({"user_id": int(uid), "nickname": nick, "card": ""})
            else:
                members.append({"user_id": int(item), "nickname": f"user_{item}", "card": ""})

        self.manager.api.set_mock_members(int(group_id), members)
        return f"{GREEN}✓ 群 {group_id} 已预设 {len(members)} 个成员{RESET}"

    async def _cmd_run(self, args: list[str]) -> str:
        if not args:
            return f"{RED}用法: run <test_file.json>{RESET}"

        from debug.runner import run_test_file
        path = Path(args[0])
        if not path.exists():
            return f"{RED}文件不存在: {path}{RESET}"

        report = await run_test_file(str(path), self.manager)
        return str(report)

    def _show_history(self) -> str:
        if not self.history:
            return f"{YELLOW}(无历史记录){RESET}"

        lines = [f"{CYAN}历史记录 ({len(self.history)}):{RESET}"]
        for i, (cmd, result) in enumerate(self.history[-20:], 1):
            status = f"{GREEN}✓{RESET}" if (result and not result.error) else f"{RED}✗{RESET}"
            lines.append(f"  {i}. {status} {cmd[:60]}")
        return "\n".join(lines)


async def run_cli(dispatcher: CommandDispatcher, dm: DataManager, cfg: dict):
    """启动 CLI 交互式 REPL（阻塞直到用户输入 quit）。"""
    manager = DebugManager.from_config(cfg)
    session = CLISession(manager)

    print(f"\n{BOLD}{CYAN}═══ HollowGroupManager 调试 CLI ═══{RESET}")
    print(f"  输入 {BOLD}help{RESET} 查看命令，{BOLD}quit{RESET} 退出\n")

    loop = asyncio.get_event_loop()

    while True:
        try:
            line = await loop.run_in_executor(None, input, PROMPT)
        except EOFError:
            print()
            break

        try:
            output = await session.handle(line)
        except Exception as e:
            logger.exception("CLI 命令异常")
            print(f"{RED}内部错误: {e}{RESET}")
            continue

        if output is None:
            break
        if output:
            print(output)
            print()

    print(f"\n{CYAN}调试 CLI 已退出。{RESET}")
