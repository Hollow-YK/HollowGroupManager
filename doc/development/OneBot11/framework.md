# OneBot11 框架开发

本文档覆盖框架层的开发：`bot/` 通信层、`core/dispatcher.py` 核心中枢、WebSocket 协议和入口流程。

## 入口流程（main.py）

`main.py` 作为应用入口，负责装配和启动所有组件：

```python
async def main():
    cfg = load_config()                          # 加载/生成 config.json
    setup_logging(cfg["log"])                    # 按配置重建日志
    api = OneBotAPI(...)                         # 初始化 HTTP API
    dm = DataManager(...)                        # 初始化数据管理器

    # 创建 dispatcher — 功能模块的唯一依赖入口
    dispatcher = CommandDispatcher(api, dm, wake_words, super_admins, render_enabled)
    dispatcher.load()                            # 加载全局 command.json + 各配置数据

    # 功能模块自行注册指令和事件监听
    dispatcher.register_command("help", HelpModule(dispatcher).handle, global_check=True)
    dispatcher.register_command("punish_do", PunishModule(dispatcher).handle)
    dispatcher.register_event("notice.group_increase", PunishModule(dispatcher).on_member_join)
    # ... 其他模块同理

    ws = OneBotWS(...)                           # 初始化 WebSocket
    await ws.start()                             # 启动 WS
```

关键步骤：
1. **加载配置** — `load_config()` 首次运行生成默认 `config.json` 后退出
2. **初始化组件** — API、DataManager、CommandDispatcher
3. **加载数据** — `dispatcher.load()` 扫描 `data/` 子目录，加载所有配置
4. **注册功能模块** — 各模块通过 `register_command` / `register_event` 注册
5. **启动 WS** — 根据 `mode` 启动正向/反向连接

## 通信层 — bot/

通信层封装 OneBot v11 协议的 HTTP 和 WebSocket 两种传输，对功能模块完全透明。

### bot/api.py — API 调用封装

`OneBotAPI` 类提供统一的 API 调用接口，支持 HTTP 和 WS 两种传输：

```python
class OneBotAPI:
    def __init__(self, http_url: str = "", access_token: str = ""): ...
    def set_ws_send(self, send: WSSend): ...         # 注入 WS 发送通道
    def handle_ws_response(self, msg: dict): ...      # 处理 WS 上的 API 响应
```

**传输策略**：
- 有 `http_url` → 走 HTTP POST（`_call_http`）
- 无 `http_url` 但有 `_ws_send` → 走 WS（`_call_ws`）

**WS 调用流程**（Universal 模式）：
1. 构造 `{"action": ..., "params": ..., "echo": "<counter>"}`
2. 创建 `asyncio.Future` 存入 `_ws_responses[echo]`
3. 通过 WS 发送请求
4. `await` Future 等待响应（10 秒超时）
5. 收到响应时 `handle_ws_response` 将 Future resolve

对外提供的语义化 API：

| 方法 | OneBot Action | 说明 |
| --- | --- | --- |
| `send_group_msg(group_id, message)` | `send_group_msg` | 发送群消息 |
| `get_group_member_list(group_id)` | `get_group_member_list` | 获取群成员列表 |
| `set_group_kick(group_id, user_id, reject)` | `set_group_kick` | 踢出成员 |
| `set_group_ban(group_id, user_id, duration)` | `set_group_ban` | 禁言（秒） |
| `is_member_in_group(group_id, user_id)` | — | 组合查询，检查成员是否在群 |
| `get_muted_members(group_id)` | — | 组合查询，获取被禁言成员 |

### bot/client.py — WebSocket 连接管理

`OneBotWS` 类管理 WebSocket 连接，支持正向和反向两种模式：

```python
class OneBotWS:
    def __init__(self, access_token: str = ""): ...
    def on_event(self, post_type: str, h: EventHandler): ...     # 注册事件监听
    def on_api(self, h: APIHandler): ...                          # 注册 API 处理（反向模式）
    def on_api_response(self, h: APIResponseHandler): ...         # 注册 API 响应处理
    async def send(self, raw: str): ...                           # 通过当前连接发送数据
    async def connect(self, ws_url: str): ...                     # 正向 WS
    async def serve(self, host: str, port: int): ...              # 反向 WS
```

**正向 WS** (`connect`)：
- Bot 主动连接 OneBot 的 WS 地址
- 连接断开自动重连（5 秒间隔）
- 支持 Bearer Token 鉴权

**反向 WS** (`serve`)：
- Bot 启动 WS 服务器，OneBot 连接过来
- 通过 `X-Client-Role` 头部识别客户端角色

**消息分发** (`_handle_ws`)：
```
收到 WS 消息
  ├── post_type 存在 → 事件 → _dispatch_event → 按 post_type 分发给注册的 handler
  ├── action 存在   → API 调用（反向模式）→ _dispatch_api → 执行并回复
  └── echo + status → API 响应 → _api_response_handler → resolve Future
```

### bot/handler.py — 事件桥接

`EventHandler` 将 OneBot v11 原始事件桥接到 `CommandDispatcher`：

```python
class EventHandler:
    async def on_message(self, event: dict):  # 消息事件 → cmd.handle_message
    async def on_notice(self, event: dict):   # 通知事件 → cmd.handle_notice
    async def on_request(self, event: dict):  # 请求事件（暂不处理）
```

## 核心层 — core/dispatcher.py

`CommandDispatcher` 是框架中枢，提供三种能力：

### 1. 注册接口

```python
# 注册指令处理器
def register_command(self, internal: str, handler: CmdHandler,
                     global_check: bool = False) -> None

# 注册事件监听器
def register_event(self, event_type: str, handler: EventListener) -> None
```

处理器签名：
```python
# 指令处理器: (level, sender_id, group_id, parts, at_list, sender_card) -> str | None
CmdHandler = Callable[[int, str, str, list, list, str], Awaitable[Optional[str]]]

# 事件监听器: (event_dict) -> None
EventListener = Callable[[dict], Awaitable[None]]
```

`global_check=True` 的命令（如 help、config）对所有配置进行权限检查，不受群-配置关联限制。

### 2. Bot 能力 API

功能模块通过 dispatcher 调用统一的语义化 API，不直接使用 `OneBotAPI`：

```python
# 消息发送
async def send_message(self, group_id: int, text: str) -> bool
async def send_image(self, group_id: int, png_bytes: bytes) -> bool

# 管理操作
async def kick(self, group_id: int, user_id: int, reject_add: bool = False) -> bool
async def ban(self, group_id: int, user_id: int, duration_sec: int) -> bool
async def unban(self, group_id: int, user_id: int) -> bool

# 信息查询
async def get_member_list(self, group_id: int) -> list
async def is_member_in_group(self, group_id: int, user_id: int) -> bool
async def get_muted_members(self, group_id: int) -> list
```

### 3. 框架服务

Dispatcher 还提供给功能模块使用的框架服务：

```python
# 权限计算 — 查所有配置中的最高权限
def _level(self, qq: str) -> int

# 配置查找 — 查找包含此群的所有配置
def _find_configs(self, group_id: str) -> list[ConfigState]

# 获取配置的完整命令配置（配置覆盖 + 全局回退）
def _resolved_commands(self, cfg: ConfigState) -> CommandConfig

# 命令权限检查
def _check_command(self, internal: str, configs: list[ConfigState], user_level: int) -> bool

# 时长解析 — "1d2h30m" / "3" → 秒
def _parse_duration(dur: str) -> Optional[int]

# 目标解析 — @优先，否则从文本提取 QQ 号
def _resolve_target(self, at_list: List[str], text: str) -> Optional[str]
```

### 消息分发流程

```
handle_message(event)
  ├── 检查 message_type == "group"
  ├── 唤醒词匹配（遍历 wake_words）
  ├── 计算权限等级 _level(sender_id)
  ├── 解析命令名（外部名 → 内部名，通过 _cmd_map）
  ├── 查注册表 _commands[internal]
  ├── 检查命令启用 + 权限
  └── 调用 handler(level, sender_id, group_id, parts, at_list, sender_card)
```

### 数据操作服务

Dispatcher 还提供 `_add_record`、`_blacklist_add`、`_blacklist_remove` 等数据操作方法，供 punish/rp 等功能模块调用。

## 添加新的通信模式

如需新增通信模式（如仅 HTTP 长轮询），需修改：

1. `bot/api.py` — 添加对应的传输方法
2. `bot/client.py` — 添加对应的连接/接收逻辑
3. `main.py` — 在 `MODES` 元组中添加新模式名，在 `main()` 中添加启动逻辑
