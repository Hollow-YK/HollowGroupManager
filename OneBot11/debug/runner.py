"""
批量测试运行器 — 从 JSON 文件加载测试场景，顺序执行并生成报告。

测试文件格式 (JSON):
{
  "name": "测试套件名称",
  "description": "可选描述",
  "setup": {
    "super_admins": ["12345"],
    "members": {"123456": [{"user_id": 111, "nickname": "admin"}]}
  },
  "scenarios": [
    {
      "name": "test help",
      "event": {"post_type": "message", "message_type": "group", ...},
      "assert": {"reply_contains": "帮助", "no_error": true}
    }
  ]
}

支持的断言:
  reply_contains      回复包含指定文本
  reply_not_contains  回复不包含指定文本
  api_count           API 调用数量 == / >= / <= 指定值
  api_actions_include API 调用中包含指定 action
  api_actions_exclude API 调用中不包含指定 action
  no_error            无异常 (true/false)

Copyright (C) 2026  Hollow-YK  |  License: GNU AGPL v3
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from debug import DebugManager

logger = logging.getLogger("Hollow.Debug.Runner")


# ════════════════════════════════════════════════════════════════
# 数据类
# ════════════════════════════════════════════════════════════════

@dataclass
class ScenarioResult:
    """单个场景的执行结果"""
    name: str
    passed: bool = True
    error: Optional[str] = None
    failures: list[str] = field(default_factory=list)
    elapsed_ms: float = 0

    @property
    def status_icon(self) -> str:
        if self.error and not self.failures:
            return "⚠"
        return "✓" if self.passed else "✗"


@dataclass
class TestReport:
    """测试报告"""
    name: str = ""
    scenarios: list[ScenarioResult] = field(default_factory=list)
    total_ms: float = 0

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.passed and not s.error)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.scenarios if not s.passed)

    @property
    def errors(self) -> int:
        return sum(1 for s in self.scenarios if s.error and s.passed)

    @property
    def total(self) -> int:
        return len(self.scenarios)

    def __str__(self) -> str:
        lines = [
            "",
            f"{'='*50}",
            f"  测试报告: {self.name}",
            f"{'='*50}",
        ]
        for i, s in enumerate(self.scenarios, 1):
            icon = s.status_icon
            line = f"  {i:2d}. [{icon}] {s.name} ({s.elapsed_ms:.0f}ms)"
            lines.append(line)
            if s.error:
                lines.append(f"      错误: {s.error}")
            for f in s.failures:
                lines.append(f"      断言失败: {f}")

        lines.append(f"{'='*50}")
        passed_str = f"通过: {self.passed}"
        failed_str = f"失败: {self.failed}"
        error_str = f"异常: {self.errors}" if self.errors else ""
        total_str = f"共 {self.total} 个场景, 耗时 {self.total_ms:.0f}ms"
        lines.append(f"  {passed_str}  {failed_str}  {error_str}  {total_str}")
        lines.append(f"{'='*50}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "total": self.total,
            "total_ms": round(self.total_ms, 1),
            "scenarios": [
                {
                    "name": s.name,
                    "passed": s.passed,
                    "error": s.error,
                    "failures": s.failures,
                    "elapsed_ms": round(s.elapsed_ms, 1),
                }
                for s in self.scenarios
            ],
        }


# ════════════════════════════════════════════════════════════════
# 断言引擎
# ════════════════════════════════════════════════════════════════

def _check_assertions(assertions: dict, reply: Optional[str],
                      api_actions: list[str], api_count: int,
                      has_error: bool) -> list[str]:
    """检查断言，返回失败的断言描述列表"""
    failures = []

    if "no_error" in assertions:
        expect_no_error = bool(assertions["no_error"])
        if expect_no_error and has_error:
            failures.append(f"no_error: 期望无异常，实际有异常")
        elif not expect_no_error and not has_error:
            failures.append(f"no_error: 期望有异常，实际无异常")

    if "reply_contains" in assertions:
        expected = str(assertions["reply_contains"])
        if not reply or expected not in reply:
            failures.append(
                f"reply_contains: 回复中未找到 {expected!r}"
                + (f" (回复: {reply[:80]!r})" if reply else " (回复为空)"))

    if "reply_not_contains" in assertions:
        unexpected = str(assertions["reply_not_contains"])
        if reply and unexpected in reply:
            failures.append(f"reply_not_contains: 回复中不应包含 {unexpected!r}")

    if "api_count" in assertions:
        expected = assertions["api_count"]
        if isinstance(expected, int):
            if api_count != expected:
                failures.append(
                    f"api_count: 期望 {expected}，实际 {api_count}")
        elif isinstance(expected, dict):
            if "==" in expected and api_count != expected["=="]:
                failures.append(
                    f"api_count: 期望 =={expected['==']}，实际 {api_count}")
            if ">=" in expected and api_count < expected[">="]:
                failures.append(
                    f"api_count: 期望 >={expected['>=']}，实际 {api_count}")
            if "<=" in expected and api_count > expected["<="]:
                failures.append(
                    f"api_count: 期望 <={expected['<=']}，实际 {api_count}")

    if "api_actions_include" in assertions:
        required = assertions["api_actions_include"]
        if isinstance(required, str):
            required = [required]
        for action in required:
            if action not in api_actions:
                failures.append(
                    f"api_actions_include: API 调用中缺少 {action!r}"
                    f" (实际: {api_actions})")

    if "api_actions_exclude" in assertions:
        forbidden = assertions["api_actions_exclude"]
        if isinstance(forbidden, str):
            forbidden = [forbidden]
        for action in forbidden:
            if action in api_actions:
                failures.append(
                    f"api_actions_exclude: API 调用中不应包含 {action!r}")

    return failures


# ════════════════════════════════════════════════════════════════
# 运行器
# ════════════════════════════════════════════════════════════════

async def run_test_file(file_path: str,
                         manager: Optional["DebugManager"] = None) -> TestReport:
    """从 JSON 文件加载并运行测试场景。

    Args:
        file_path: 测试 JSON 文件路径
        manager:   可选的 DebugManager 实例。若未提供，需要
                   测试文件中包含 config 引用。
    """
    import time

    path = Path(file_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    # 如果 manager 未提供，尝试从 cfg 字段构建
    if manager is None:
        from debug import DebugManager
        # 尝试读取同目录下的 config
        cfg_path = path.parent / "config.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        else:
            cfg = {
                "plugin": {"wake_words": ["/", "!", "。"], "super_admins": [],
                           "data_dir": str(path.parent / "data")},
                "render": {"enabled": False},
            }
        manager = DebugManager.from_config(cfg)

    report = TestReport(name=data.get("name", path.stem))
    t0 = time.perf_counter()

    # ── Setup ──
    setup = data.get("setup", {})

    if "super_admins" in setup:
        manager.set_super_admins({str(a) for a in setup["super_admins"]})

    if "members" in setup:
        for gid_str, members in setup["members"].items():
            manager.api.set_mock_members(int(gid_str), members)

    if "muted" in setup:
        for gid_str, muted in setup["muted"].items():
            manager.api.set_mock_muted(int(gid_str), muted)

    # ── 执行场景 ──
    for scenario in data.get("scenarios", []):
        name = scenario.get("name", "(未命名)")
        event = scenario.get("event", {})
        assertions = scenario.get("assert", {})

        sr = ScenarioResult(name=name)

        try:
            result = await manager.inject_event(event)
            sr.elapsed_ms = result.elapsed_ms

            # 收集 API actions
            api_actions = [c.action for c in result.api_calls]

            failures = _check_assertions(
                assertions,
                reply=result.reply,
                api_actions=api_actions,
                api_count=len(result.api_calls),
                has_error=result.error is not None,
            )

            if failures:
                sr.passed = False
                sr.failures = failures

            # 如果断言中没有 no_error 但有实际错误
            if result.error and "no_error" not in assertions:
                sr.error = result.error

        except Exception as e:
            sr.passed = False
            sr.error = f"{type(e).__name__}: {e}"

        report.scenarios.append(sr)

    report.total_ms = (time.perf_counter() - t0) * 1000
    return report


async def run_test_suite(suite: dict,
                          manager: "DebugManager") -> TestReport:
    """直接运行内存中的测试套件字典。

    suite 格式与 run_test_file 的 JSON 文件格式相同。
    """
    import time

    report = TestReport(name=suite.get("name", "suite"))
    t0 = time.perf_counter()

    setup = suite.get("setup", {})
    if "super_admins" in setup:
        manager.set_super_admins({str(a) for a in setup["super_admins"]})
    if "members" in setup:
        for gid_str, members in setup["members"].items():
            manager.api.set_mock_members(int(gid_str), members)

    for scenario in suite.get("scenarios", []):
        name = scenario.get("name", "(未命名)")
        event = scenario.get("event", {})
        assertions = scenario.get("assert", {})

        sr = ScenarioResult(name=name)

        try:
            result = await manager.inject_event(event)
            sr.elapsed_ms = result.elapsed_ms
            api_actions = [c.action for c in result.api_calls]

            failures = _check_assertions(
                assertions,
                reply=result.reply,
                api_actions=api_actions,
                api_count=len(result.api_calls),
                has_error=result.error is not None,
            )
            if failures:
                sr.passed = False
                sr.failures = failures
            if result.error and "no_error" not in assertions:
                sr.error = result.error
        except Exception as e:
            sr.passed = False
            sr.error = f"{type(e).__name__}: {e}"

        report.scenarios.append(sr)

    report.total_ms = (time.perf_counter() - t0) * 1000
    return report
