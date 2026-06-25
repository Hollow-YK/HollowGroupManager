# 版本详细对比

HollowGroupManager 提供两个版本：**QFun 版**（Android 插件）和 **OneBot11 版**（Python 服务器）。两版功能等价，仅在运行平台和实现语言上有差异。

## 功能对齐

以下方面两版**完全一致**：

| 功能 | 说明 |
|------|------|
| 指令集 | 6 个指令（`/help` `/p` `/rp` `/h` `/a` `/config`），语法和参数相同。 |
| 权限模型 | 多级（0/≥1/-1），各命令通过 `command.json` 的 `min_level` 控制 |
| 命令别名 | `command.json` 中 `names` 字段自定义（如 `["p", "punish"]`） |
| 多配置架构 | `data/<配置名>/punish/` 子目录结构，一个群可属于多个配置 |
| 命令配置 | 全局 `data/command.json` + 各配置 `command.json` 覆盖继承 |
| 三步检查 | 成员在群 → 状态检查 → 执行 → 执行后验证 |
| 原子写入 | `.tmp` 文件 → 重命名，加载失败自动尝试 `.tmp` 恢复 |
| 数据兼容 | 相同 JSON 格式，`.tmp` 恢复机制 |
| 许可协议 | AGPL v3.0 |

## 平台差异

| 维度 | QFun 版 | OneBot11 版 |
|------|---------|-------------|
| **语言** | Java / BeanShell | Python 3.10+ |
| **运行平台** | Android（QFun 插件框架） | Linux / Windows / macOS |
| **QQ 接口** | QFun Plugin API（进程内直接调用） | OneBot v11 协议（HTTP + WebSocket） |
| **代码组织** | 单文件（`main.java`，~2500 行） | 模块化（`bot/` + `core/`，7 个 `.py` 文件） |
| **数据模型** | 手动 `toMap()` / `fromMap()` | Pydantic v2 自动序列化 |
| **JSON 库** | `org.json` | Python `json` 标准库 |
| **并发模型** | `Collections.synchronizedList` + `synchronized` 块 | `asyncio` 协程（单线程事件循环） |
| **图片渲染** | Android `Canvas` / `Paint`（系统字体，始终启用） | Pillow（需搜索字体路径，可通过配置关闭） |
| **配置格式** | `config.properties`（Java Properties） | `config.json`（JSON） |
| **依赖管理** | 零依赖（QFun 框架内置） | `requirements.txt`（pip/uv） |

---

## QQ 接口

### QFun Plugin API

QFun 版运行在 Android QQ 进程内，通过 QFun 框架直接调用 QQ 内部 API。所有 API 方法是**全局函数**，无需导入或传递上下文。

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
- **BeanShell 环境** — 支持 Java 8+ 语法、Lambda、Kotlin `?.`，不支持注解
- **类型陷阱** — 数值可能以 `bsh.Primitive` 形式出现，需 `String.valueOf()` + `parseXxx()` 中转
- **线程模型** — 回调在 IO 线程，UI 操作需切换主线程

### OneBot v11 协议

OneBot11 版通过标准 HTTP / WebSocket 协议通信，完全独立于 QQ 进程。

```python
# HTTP API 调用
await api.send_group_msg(group_id, message)
await api.set_group_kick(group_id, user_id)
await api.set_group_ban(group_id, user_id, duration)

# WebSocket 事件接收
async for event in ws_client:
    if event["post_type"] == "message":
        handle_message(event)
```

特点：
- **网络通信** — HTTP POST 调用 API，WebSocket 推送事件
- **四种通信模式** — 正向/反向 WS，HTTP+WS 组合（详见下方）
- **Bearer Token 鉴权**
- **跨平台** — 可在服务器运行
- **异步模型** — 基于 `asyncio` + `aiohttp` + `websockets`

---

## 代码组织

### QFun 版 — 单文件

```
main.java  (~2500 行)
├── 数据模型          ConfigInfo / CommandItem / CommandConfig / ConfigState
│                     PunishRecord / BlacklistItem
├── 全局变量与配置     wakeWords / superAdmins / configs / globalCommands
├── JSON 读写          .tmp 原子写入 + 恢复
├── 数据持久化         各配置 loadConfigXxx / saveConfig
├── 初始化             init() — 扫描配置子目录，构建命令名映射
├── 消息入口           onMsg() — 唤醒词匹配 → 命令名解析 → 权限检查 → 路由
├── 指令处理           cmdHelp / cmdPunish / cmdRevoke / cmdQuery / cmdPermission / cmdConfig
├── 图片渲染           generateHelpImage / generatePunishRecordTableImage
├── 群事件             joinGroup() — 黑名单自动踢人
└── 生命周期           unLoadPlugin()
```

### OneBot11 版 — 模块化

```
OneBot11/
├── main.py              # 入口（asyncio 启动）
├── bot/                 # 通信层
│   ├── api.py           # HTTP/WS API 封装
│   ├── client.py        # WebSocket 客户端
│   └── handler.py       # 事件分发
├── core/                # 业务逻辑
│   ├── models.py        # Pydantic 数据模型
│   ├── data_manager.py  # JSON 持久化
│   ├── commands.py      # 指令实现
│   └── render.py        # 图片生成（Pillow）
├── tools/               # 独立工具
│   └── migrate.py       # 旧版数据迁移
└── data/                # 运行时数据
    ├── command.json     # 全局命令配置
    └── <配置名>/         # 各配置独立目录
```

按职责分层：通信层（`bot/`）与业务逻辑（`core/`）分离。

---

## 数据模型

### QFun 版 — 手动序列化

```java
class PunishRecord {
    int id;
    long sender;
    // ...

    Map<String, Object> toMap() {           // 序列化
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", id);
        map.put("sender", sender);
        return map;
    }

    static PunishRecord fromMap(Map<String, Object> map) {  // 反序列化
        PunishRecord r = new PunishRecord();
        r.id = Integer.parseInt(String.valueOf(map.get("id")));
        r.sender = Long.parseLong(String.valueOf(map.get("sender")));
        return r;
    }
}
```

注意点：
- 必须用 `String.valueOf()` + `parseXxx()` 模式，**不能直接 cast**（BeanShell 的 `bsh.Primitive` 会导致 `ClassCastException`）
- 类名避免与 Java 标准库冲突（`Record` → `PunishRecord`）
- 所有可选字段需空值保护（`map.get("x") != null ? ... : ""`）

### OneBot11 版 — Pydantic 自动序列化

```python
class PunishRecord(BaseModel):
    id: int
    sender: int
    # ...

    @model_validator(mode='before')
    @classmethod
    def coerce_int(cls, data):
        """将字符串数字转为 int，兼容 Java 版数据"""
        for field in ('id', 'sender', 'time', 'target'):
            if field in data and isinstance(data[field], str):
                data[field] = int(data[field])
        return data
```

特点：
- 声明式字段定义，自动校验类型
- `model_dump()` / `model_validate()` 自动序列化
- 通过 `model_validator` 兼容 Java 版可能的字符串数字

---

## 图片渲染

| | QFun 版 | OneBot11 版 |
|---|---|---|
| **库** | Android Graphics | Pillow (PIL) |
| **API** | `Canvas.drawText` / `drawRoundRect` / `drawLine` | `ImageDraw.text` / `rounded_rectangle` / `line` |
| **字体** | 系统字体（`Typeface.DEFAULT_BOLD`） | 需搜索系统字体路径 |
| **输出** | `sendPic()` 直接发送 | 保存 PNG → Base64 图片消息 |
| **降级** | 始终启用 | `render.enabled: false` 降级为纯文本 |
| **陷阱** | `Paint.Style.STROKE` 用后须恢复 `FILL`；int/float 混合运算在 BeanShell 中可能产生 `double` 导致 `drawText` 找不到匹配重载 | 中文字体需手动配置路径 |

---

## 并发模型

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
- `synchronizedList` + `synchronized` 块保证线程安全
- 无异步 IO — 所有 API 调用同步

### OneBot11 版

```python
# asyncio 协程
async def handle_message(self, event: dict): ...

# HTTP API 调用
async with aiohttp.ClientSession() as session:
    async with session.post(url, json=payload) as resp: ...
```

- 单线程事件循环，所有操作异步非阻塞
- 无需显式加锁 — 同一时刻只有一个协程运行
- HTTP/WS 调用通过 `await` 挂起，不阻塞其他任务

---

## 配置格式

### QFun 版 — `config.properties`

```properties
wakeWords=/,!,。
superAdmins=12345,10000
dataDir=data
```

| 字段 | 说明 |
|------|------|
| `wakeWords` | 唤醒前缀，逗号分隔 |
| `superAdmins` | 超级管理员 QQ，逗号分隔（**必须填发指令者的 QQ，非 Bot QQ**） |
| `dataDir` | 数据目录名，相对路径 |

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
  "render": { "enabled": true },
  "log": {
    "log_to_file": true,
    "log_level": "INFO",
    "log_dir": "logs"
  }
}
```

OneBot11 版多出 `onebot`（通信配置）、`render`（渲染开关）、`log`（日志）三个配置段。

---

## OneBot11 通信模式

OneBot11 版支持四种通信模式，通过 `onebot.mode` 选择：

| 模式 | `mode` 值 | API 通道 | 事件通道 |
|------|-----------|----------|----------|
| HTTP + 正向 WS | `http_ws` | HTTP POST | 正向 WS（Bot 连 OneBot） |
| 正向 WS Universal | `ws` | WS | WS（同一连接） |
| 反向 WS Universal | `ws_reverse` | WS | 反向 WS（OneBot 连 Bot） |
| HTTP + 反向 WS | `http_ws_reverse` | HTTP POST | 反向 WS |

---

## 选择指南

| 场景 | 推荐版本 |
|------|----------|
| 只有 Android 手机，QQ 已装 QFun | QFun 版 |
| 有 Linux/Windows 服务器，想 24h 运行 | OneBot11 版 |
| 使用 NapCat / LLOneBot 等 OneBot 实现 | OneBot11 版 |
| 需要单文件零依赖部署 | QFun 版 |
| 需要模块化、可扩展的代码 | OneBot11 版 |
