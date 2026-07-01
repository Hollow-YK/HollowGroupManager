# 调试与测试开发

本文档介绍 `debug/` 模块的设计、使用和扩展方式。

## 架构

```
debug/
├── __init__.py      # DebugManager + DebugAPI + DebugResult + APICall
├── cli.py           # CLI 交互式 REPL
├── http_server.py   # HTTP 调试端点
├── runner.py        # JSON 批量测试运行器
└── examples/        # 示例测试文件
    └── smoke_test.json
```

三层结构：

1. **核心引擎** (`__init__.py`) — `DebugManager` 构建完整测试管线，`DebugAPI` 模拟 OneBot API
2. **用户接口** (`cli.py`, `http_server.py`) — 提供交互式和程序化的测试入口
3. **测试框架** (`runner.py`) — JSON 驱动的批量测试 + 断言引擎

## 核心类

### DebugAPI

与 `bot/api.py` 的 `OneBotAPI` 接口完全一致（鸭子类型），所有方法记录调用参数并返回模拟成功结果：

```python
class DebugAPI:
    def __init__(self):
        self.calls: list[APICall] = []         # API 调用记录
        self._members: dict[int, list[dict]] = {}  # 模拟群成员
        self._muted: dict[int, list[dict]] = {}    # 模拟禁言成员

    # 消息发送 → 记录并返回模拟 message_id
    async def send_group_msg(self, group_id, message) -> Optional[int]

    # 管理操作 → 记录并返回 True
    async def set_group_kick(self, group_id, user_id, reject_add_request=False) -> bool
    async def set_group_ban(self, group_id, user_id, duration) -> bool

    # 信息查询 → 返回预设模拟数据
    async def get_group_member_list(self, group_id) -> Optional[list[dict]]
    async def is_member_in_group(self, group_id, user_id) -> bool
    async def get_muted_members(self, group_id) -> list[dict]
    async def get_login_info(self) -> Optional[dict]

    # 请求处理 → 记录并返回 True
    async def set_group_add_request(self, flag, sub_type, approve, reason="") -> bool
```

**扩展新 API**：若功能模块新增了 OneBot API 调用，需要在 `DebugAPI` 中添加同名方法。

### DebugManager

构建完整测试管线（DataManager → CommandDispatcher → 模块注册 → EventHandler）：

```python
class DebugManager:
    api: DebugAPI              # 模拟 API 实例
    dispatcher: CommandDispatcher  # 指令分发器（注入 DebugAPI）
    handler: EventHandler      # 事件处理器（注入 DebugAPI）

    @classmethod
    def from_config(cls, cfg: dict, data_dir="data/test") -> "DebugManager"
    async def inject_event(self, event: dict) -> DebugResult
    async def inject_message(self, group_id, user_id, raw_message, **kwargs) -> DebugResult
    async def inject_notice(self, notice_type, group_id, user_id, **kwargs) -> DebugResult
    async def inject_request(self, request_type, sub_type, group_id, user_id, **kwargs) -> DebugResult
    def set_super_admins(self, admins: set[str])
```

**事件注入流程**：

```
inject_event(event_dict)
  → EventHandler.on_message/on_notice/on_request(event_dict)
    → CommandDispatcher.handle_message/handle_notice/handle_request(event_dict)
      → 功能模块 handler(event)
        → dispatcher.send_message() / kick() / ban() / ...
          → DebugAPI（记录调用、返回模拟结果）
  → 收集 reply + api_calls → DebugResult
```

### DebugResult

```python
@dataclass
class DebugResult:
    reply: Optional[str] = None       # 消息回复文本（仅消息事件）
    api_calls: list[APICall] = []     # API 调用记录
    error: Optional[str] = None       # 异常信息
    elapsed_ms: float = 0             # 处理耗时

@dataclass
class APICall:
    action: str                       # API 动作名
    params: dict                      # 调用参数
    result: Any = None                # 返回结果
    timestamp: float                  # 调用时间戳
```

## CLI REPL

`debug/cli.py` 提供交互式终端调试：

| 命令 | 格式 | 说明 |
|------|------|------|
| `msg` | `msg group=<id> user=<id> text="<raw>" [at=<qq>] [card=<name>]` | 模拟群消息 |
| `notice` | `notice <type> group=<id> user=<id> [key=value ...]` | 模拟通知事件 |
| `request` | `request <type> <sub> group=<id> user=<id> [key=value ...]` | 模拟请求事件 |
| `members` | `members group=<id> set <qq>:<nick> [...]` | 预设群成员 |
| `run` | `run <test_file.json>` | 运行批量测试 |
| `help` | `help` | 显示帮助 |
| `history` | `history` | 查看最近注入记录 |
| `quit` | `quit` | 退出 |

解析引擎：`shlex.split()` 处理引号参数，`key=value` 自动解析为参数字典，`key=val1,val2` 解析为列表。

## HTTP 端点

`debug/http_server.py` 基于 `aiohttp` 提供 REST API：

| 端点 | 方法 | 请求体 | 响应 |
|------|------|--------|------|
| `/debug/event` | POST | OneBot 事件 JSON | `DebugResult` JSON |
| `/debug/message` | POST | `{"group_id":..., "user_id":..., "raw_message":...}` | `DebugResult` JSON |
| `/debug/members` | POST | `{"group_id":..., "members":[...]}` | `{"status":"ok", ...}` |
| `/debug/run` | POST | `{"file": "path/to/test.json"}` | `TestReport` JSON |
| `/debug/health` | GET | — | `{"status":"ok"}` |

**启动方式**：`config.json` 中 `debug.enabled: true` 时自动在 `127.0.0.1:<port>` 启动。

## 批量测试

`debug/runner.py` 从 JSON 文件加载测试场景：

### 测试文件格式

```json
{
  "name": "测试套件名称",
  "description": "可选描述",
  "setup": {
    "super_admins": ["10001"],
    "members": {"123456": [{"user_id": 111, "nickname": "Alice"}]}
  },
  "scenarios": [
    {
      "name": "场景名",
      "event": { ... },
      "assert": { ... }
    }
  ]
}
```

### 支持的断言

| 断言 | 值类型 | 说明 |
|------|--------|------|
| `no_error` | `bool` | 期望无异常 |
| `reply_contains` | `str` | 回复包含指定文本 |
| `reply_not_contains` | `str` | 回复不包含指定文本 |
| `api_count` | `int` 或 `{"==": n}` / `{">=": n}` / `{"<=": n}` | API 调用数量断言 |
| `api_actions_include` | `str` 或 `[str, ...]` | API 调用中包含指定 action |
| `api_actions_exclude` | `str` 或 `[str, ...]` | API 调用中不包含指定 action |

### 运行

```bash
# CLI REPL 中
debug> run debug/examples/smoke_test.json

# HTTP
curl -X POST http://127.0.0.1:8765/debug/run \
  -H "Content-Type: application/json" \
  -d '{"file":"debug/examples/smoke_test.json"}'

# Python 脚本
from debug import DebugManager
from debug.runner import run_test_file

manager = DebugManager.from_config(cfg)
report = await run_test_file("debug/examples/smoke_test.json", manager)
print(report)
```

## 与 main.py 的集成

`main.py` 在末尾检查 `debug.enabled`：

```python
debug_cfg = cfg.get("debug", {})
if debug_cfg.get("enabled", False):
    from debug.cli import run_cli
    from debug.http_server import start_http_server
    # HTTP 服务器后台启动
    tasks.append(asyncio.create_task(start_http_server(http_port, ...)))
    # CLI REPL 阻塞主线程
    await run_cli(dispatcher, dm, cfg)
    return  # 不连接真实 OneBot
```

调试模式下 **不连接真实 OneBot 服务端**，CLI REPL 退出时自动保存数据并关闭。

## 添加新调试功能

### 为 DebugAPI 添加新 API 方法

```python
# 在 debug/__init__.py 的 DebugAPI 中添加
async def new_api_method(self, param1: int, param2: str) -> bool:
    return self._record("new_api_method", {"param1": param1, "param2": param2})
```

### 为 CLI 添加新命令

```python
# 在 debug/cli.py 的 CLISession 中添加
async def _cmd_mycommand(self, args: list[str]) -> str:
    kv = _parse_kv(args)
    # ... 处理逻辑
    result = await self.manager.inject_event({...})
    return _format_result(result)
```

然后在 `handle()` 方法中注册该命令。

### 添加新的断言类型

```python
# 在 debug/runner.py 的 _check_assertions() 中添加
if "my_assertion" in assertions:
    expected = assertions["my_assertion"]
    if not some_condition:
        failures.append(f"my_assertion: 期望 {expected}，实际 {actual}")
```

## 注意事项

1. **调试模式不连 OneBot**：`debug.enabled: true` 时 Bot 不会尝试连接 OneBot 服务端
2. **DebugAPI 方法需同步更新**：若 `OneBotAPI` 新增方法，务必在 `DebugAPI` 中添加对应方法
3. **测试数据隔离**：建议使用独立的数据目录（如 `testdata`），避免污染生产数据
4. **渲染默认关闭**：调试模式下 `render_enabled=False`，减少依赖
5. **类型检查**：`DebugAPI` 使用鸭子类型，与 `OneBotAPI` 无继承关系，IDE 可能报警告（实际运行无影响）
