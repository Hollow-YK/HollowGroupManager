# 版本详细对比

本文档详细对比 HollowGroupManager 两个版本在架构、接口、部署等方面的差异。

## 总览

| 维度 | QFun 版 | OneBot11 版 |
| --- | --- | --- |
| **语言** | Java / BeanShell | Python 3.10+ |
| **运行平台** | Android（QFun 插件） | 任意平台（Linux / Windows / macOS） |
| **QQ 接口** | QFun Plugin API（直接调用） | OneBot v11 协议（HTTP / WebSocket） |
| **代码组织** | 单文件（`main.java`，~1900 行） | 模块化（7 个 `.py` 文件） |
| **图形渲染** | Android `Bitmap` / `Canvas` / `Paint` | Pillow（跨平台） |
| **数据模型** | 手动 `toMap()` / `fromMap()` | Pydantic v2 自动序列化 |
| **JSON 库** | `org.json` | Python `json` 标准库 |
| **并发模型** | `Collections.synchronizedList` | `asyncio` 协程 |
| **配置格式** | `config.properties`（Java Properties） | `config.json`（JSON） |
| **依赖管理** | 无（QFun 框架内置） | `requirements.txt`（pip/uv） |

## QQ 接口对比

### QFun Plugin API

QFun 版运行在 Android QQ 进程内，通过 QFun 框架直接调用 QQ 内部 API。所有 API 方法为**全局函数**，无需导入或传递上下文：

```java
// 直接在脚本任意位置调用
List members = getGroupMemberList(groupCode);
shutUp(groupCode, qq, duration);
kickGroup(groupCode, qq, false);
sendMsg(peerUin, message, 2);
log("info.log", "message");
```

特点：
- **零网络开销** — 方法调用走进程内 IPC
- **BeanShell 环境** — 支持 Java 8+ 语法、Lambda、Kotlin `?.` 安全调用，但不支持注解
- **类型陷阱** — 数值可能以 `bsh.Primitive` 出现，需 `String.valueOf()` 中转
- **线程模型** — 回调在 IO 线程，UI 操作需切换主线程

### OneBot v11 协议

OneBot11 版通过标准 HTTP / WebSocket 协议与 QQ 客户端通信，完全独立于 QQ 进程：

```python
# HTTP API 调用
await api.send_group_msg(group_id, message)
await api.set_group_kick(group_id, user_id)
await api.set_group_ban(group_id, user_id, duration)
members = await api.get_group_member_list(group_id)

# WebSocket 事件接收
async for event in ws_client:
    if event["post_type"] == "message":
        handle_message(event)
```

特点：
- **网络通信** — HTTP POST 调用 API，WebSocket 推送事件
- **四种通信模式** — 正向/反向 WS，HTTP+WS 组合
- **Bearer Token 鉴权**
- **跨平台** — 可在服务器运行，不依赖 Android 环境
- **异步模型** — 基于 `asyncio` + `aiohttp` + `websockets`

详见 [OneBot11 通信模式详解](#onebot11-通信模式)。

## 代码组织对比

### QFun 版 — 单文件架构

```
main.java  (~1900 行)
├── 全局变量和配置（行 1-46）
├── 启动配置验证（行 47-358）
├── 数据模型（行 360-467）
│   ├── ManagementGroup
│   ├── PunishRecord
│   └── BlacklistItem
├── 初始化与持久化（行 469-683）
├── 辅助方法（行 690-760）
├── 消息入口（行 762-821）
├── 指令处理（行 823-1822）
│   ├── cmdHelp()
│   ├── cmdPunish()
│   ├── cmdRevoke()
│   ├── cmdQuery()
│   ├── cmdPermission()
│   └── cmdGroup()
├── 群事件处理（行 1825-1874）
└── 生命周期（行 1877-1879）
```

所有逻辑集中在单一 `main.java`，通过注释分隔逻辑区块。

### OneBot11 版 — 模块化架构

```
OneBot11/
├── main.py              # 入口（asyncio 启动）
├── bot/                 # 通信层
│   ├── api.py           # HTTP/WS API 封装
│   ├── client.py        # WebSocket 客户端
│   └── handler.py       # 事件分发
└── core/                # 业务逻辑
    ├── models.py         # Pydantic 数据模型
    ├── data_manager.py   # JSON 持久化
    ├── commands.py       # 指令实现
    └── render.py         # 图片生成
```

按职责分层：通信层（`bot/`）与业务逻辑（`core/`）分离。

## 数据模型对比

### QFun 版 — 手动序列化

```java
class PunishRecord {
    int id;
    long sender;
    long time;
    // ...

    Map<String, Object> toMap() {
        Map<String, Object> map = new HashMap<>();
        map.put("id", id);
        map.put("sender", sender);
        // ...
        return map;
    }

    static PunishRecord fromMap(Map<String, Object> map) {
        PunishRecord r = new PunishRecord();
        r.id = Integer.parseInt(String.valueOf(map.get("id")));
        r.sender = Long.parseLong(String.valueOf(map.get("sender")));
        // ... String.valueOf() 避免 bsh.Primitive 类型异常
        return r;
    }
}
```

关键注意点：
- 必须用 `String.valueOf()` + `parseXxx()` 模式，**不能直接 cast**
- 类名避免与 Java 标准库冲突（如 `Record` → `PunishRecord`）
- 所有可选字段需空值保护

### OneBot11 版 — Pydantic 自动序列化

```python
from pydantic import BaseModel, Field, model_validator

class PunishRecord(BaseModel):
    id: int
    sender: int
    time: int
    # ...

    @model_validator(mode='before')
    @classmethod
    def coerce_int(cls, data: Any) -> Any:
        # 兼容 Java 版的字符串数字
        for field in ('id', 'sender', 'time', 'from_group', 'target'):
            if field in data and isinstance(data[field], str):
                data[field] = int(data[field])
        return data
```

特点：
- 声明式字段定义，自动校验类型
- `model_dump()` / `model_validate()` 自动序列化/反序列化
- 通过 `model_validator` 实现 Java 版兼容

## 图片渲染对比

| | QFun 版 | OneBot11 版 |
| --- | --- | --- |
| **库** | Android Graphics | Pillow (PIL) |
| **API** | `Bitmap` / `Canvas` / `Paint` / `Typeface` | `Image` / `ImageDraw` / `ImageFont` |
| **字体** | 系统字体，`Typeface.DEFAULT_BOLD` | 需搜索系统字体路径（Windows/macOS/Linux） |
| **输出** | 直接通过 `sendPic()` 发送 | 保存为 PNG → 通过 `send_group_msg` 发送图片消息 |
| **可选性** | 始终启用 | 可通过 `render.enabled: false` 降级为纯文本 |

## 并发模型对比

### QFun 版

```java
// 数据集合用同步包装器
List<PunishRecord> records = Collections.synchronizedList(new ArrayList<>());

// 初始化用双重检查锁
if (!initialized) {
    synchronized (initLock) {
        if (!initialized) { init(); initialized = true; }
    }
}
```

- `onMsg` 和 `joinGroup` 可能在不同线程并发
- 用 `synchronizedList` + `synchronized` 块保证线程安全
- 无异步 IO — 所有 API 调用同步

### OneBot11 版

```python
# asyncio 协程
async def handle_message(self, event: dict):
    ...

async def handle_notice(self, event: dict):
    ...

# HTTP API 调用
async with aiohttp.ClientSession() as session:
    async with session.post(url, json=payload) as resp:
        ...
```

- 单线程事件循环，所有操作异步非阻塞
- 无需显式加锁 — 同一时刻只有一个协程在运行
- HTTP/WS 调用通过 `await` 挂起，不阻塞其他任务

## OneBot11 通信模式

OneBot11 版支持四种通信模式，通过 `config.json` 中 `onebot.mode` 选择：

| 模式 | `mode` 值 | API 通道 | 事件通道 | 适用场景 |
| --- | --- | --- | --- | --- |
| HTTP + 正向 WS | `http_ws` | HTTP POST | 正向 WS（Bot 连 OneBot） | 本地开发，最常用 |
| 正向 WS Universal | `ws` | WS | WS（同一连接） | 单端口部署 |
| 反向 WS Universal | `ws_reverse` | WS | 反向 WS（OneBot 连 Bot） | 内网穿透 |
| HTTP + 反向 WS | `http_ws_reverse` | HTTP POST | 反向 WS | Bot 有公网 IP |

### 模式 A：HTTP + 正向 WS（默认）

```
OneBot (服务端)                      HollowGroupManager (客户端)
┌─────────────────┐                 ┌──────────────────────────┐
│ HTTP :3000      │◄─── POST ──────│ api.py    (主动调用 API)  │
│ WS :3001        │── 推送事件 ──→│ client.py (主动连过去)     │
└─────────────────┘                 └──────────────────────────┘
```

### 模式 B：正向 WS Universal

```
OneBot (服务端)                      HollowGroupManager (客户端)
┌─────────────────┐                 ┌──────────────────────────┐
│ WS :3001  /     │◄═ 双向 JSON ═►│ client.py                │
│                 │  事件 ←  → API │ (一条连接搞定一切)         │
└─────────────────┘                 └──────────────────────────┘
```

### 模式 C：反向 WS Universal

```
OneBot (客户端)                      HollowGroupManager (服务端)
┌─────────────────┐                 ┌──────────────────────────┐
│ WS 客户端        │── 连接 ──────→│ WS :8080   (Bot 监听)     │
│                 │◄═ 双向 JSON ═►│ API + 事件 一条连接        │
└─────────────────┘                 └──────────────────────────┘
```

### 模式 D：HTTP + 反向 WS

```
OneBot (客户端)                      HollowGroupManager (服务端)
┌─────────────────┐                 ┌──────────────────────────┐
│ HTTP :3000      │◄─── POST ──────│ api.py    (主动调用 API)  │
│ WS 客户端        │── 推送事件 ──→│ WS :8080   (Bot 监听)     │
└─────────────────┘                 └──────────────────────────┘
```

## 配置差异

### QFun 版 — `config.properties`

```properties
wakeWords=/,!,。
superAdmins=12345,10000
dataDir=data
```

| 字段 | 说明 |
| --- | --- |
| `wakeWords` | 唤醒前缀，逗号分隔，不含空格 |
| `superAdmins` | 超级管理员 QQ，逗号分隔 |
| `dataDir` | 数据目录，相对路径 |

### OneBot11 版 — `config.json`

```json
{
  "onebot": {
    "mode": "http_ws",
    "http_url": "http://127.0.0.1:3000",
    "ws_url": "ws://127.0.0.1:3001",
    "ws_reverse_port": 0,
    "access_token": ""
  },
  "plugin": {
    "wake_words": ["/", "!", "。"],
    "super_admins": ["123456789"],
    "data_dir": "data"
  },
  "render": {
    "enabled": true
  },
  "log": {
    "log_to_file": true,
    "log_level": "INFO",
    "log_dir": "logs"
  }
}
```

| 字段 | 说明 |
| --- | --- |
| `onebot.mode` | 通信模式 |
| `onebot.http_url` | HTTP API 地址，`""` 禁用 |
| `onebot.ws_url` | 正向 WS 地址，`""` 禁用 |
| `onebot.ws_reverse_port` | 反向 WS 端口，`0` 禁用 |
| `onebot.access_token` | 鉴权令牌 |
| `plugin.wake_words` | 唤醒前缀数组 |
| `plugin.super_admins` | 超管 QQ 数组 |
| `plugin.data_dir` | 数据目录 |
| `render.enabled` | 图片渲染开关 |
| `log.log_to_file` | 是否输出日志到文件 |
| `log.log_level` | 日志等级（DEBUG / INFO / WARNING / ERROR） |
| `log.log_dir` | 日志目录，默认 `logs` |

## 共享设计

两版在以下方面保持统一：

- **指令集**：6 个指令（`/help`、`/p`、`/rp`、`/h`、`/a`、`/group`），语法和参数完全一致
- **数据格式**：4 个 JSON 文件（`groups.json`、`records.json`、`permissions.json`、`blacklist.json`），格式兼容可互换
- **权限模型**：三级（0=超管 / 1=管理员 / -1=普通成员）
- **管理组架构**：一个管理群 + 多个执行群
- **三步检查**：成员在群 → 状态检查 → 执行 → 执行后验证
- **原子写入**：`.tmp` 文件 → 重命名覆盖目标
- **许可协议**：AGPLv3

## 选择指南

| 场景 | 推荐版本 |
| --- | --- |
| 只有 Android 手机，QQ 已装 QFun | QFun 版 |
| 有 Linux/Windows 服务器，想 24h 运行 | OneBot11 版 |
| 使用 NapCat / LLOneBot 等 OneBot 实现 | OneBot11 版 |
| 需要单文件零依赖部署 | QFun 版 |
| 需要模块化、可扩展的代码 | OneBot11 版 |
| 需要远程服务器控制多个 QQ 号 | 还没支持 |
