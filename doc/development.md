# 开发文档

本文档涵盖 HollowGroupManager 两个版本的开发指南、架构设计和常见任务。

## 项目结构

```text
HollowGroupManager/
├── QFun/                          # QFun 插件版（Java/BeanShell）
│   ├── main.java                  # 单文件插件脚本（~2500 行）
│   ├── config.properties          # 唤醒词、超管、数据目录
│   ├── info.prop                  # 插件元信息（id/名称/版本/作者）
│   ├── desc.txt                   # 插件描述（QFun 列表展示）
│   ├── README.md                  # 用户文档
│   ├── AGENTS.md                  # QFun 专属开发文档
│   ├── history.txt                # 版本历史
│   ├── LICENSE                    # AGPLv3
│   └── data/                      # 运行时数据（自动生成）
├── OneBot11/                      # OneBot v11 版（Python）
│   ├── main.py                    # 入口（asyncio）
│   ├── config.json                # 配置文件
│   ├── requirements.txt           # Python 依赖
│   ├── README.md                  # 用户文档
│   ├── history.txt                # 版本历史
│   ├── LICENSE                    # AGPLv3
│   ├── bot/                       # 通信层
│   │   ├── api.py                 # HTTP/WS API 封装
│   │   ├── client.py              # WebSocket 客户端
│   │   └── handler.py             # 事件分发
│   ├── core/                      # 业务逻辑
│   │   ├── models.py              # Pydantic 数据模型
│   │   ├── data_manager.py        # JSON 持久化
│   │   ├── commands.py            # 指令实现
│   │   └── render.py              # 图片生成（Pillow）
│   ├── tools/                     # 独立工具
│   │   └── migrate.py             # 旧版数据迁移
│   ├── data/                      # 运行时数据
│   │   ├── command.json           # 全局命令配置
│   │   └── <配置名>/              # 各配置独立目录
│   │       ├── groups.json        # 通知群 + 执行群
│   │       ├── command.json       # 命令覆盖（可选）
│   │       ├── permissions.json   # 权限映射
│   │       └── punish/            # 处罚子系统
│   │           ├── records.json
│   │           └── blacklist.json
│   └── logs/                      # 日志文件（时间命名）
├── doc/                           # 项目文档
│   ├── comparison.md              # 两版详细对比
│   └── development.md             # 本文档
├── .github/workflows/release.yml  # CI 发布流程
└── LICENSE                        # AGPLv3
```

## 共享架构

两个版本共享相同的逻辑架构：

```
消息/事件 → 唤醒词匹配 → 权限检查 → 指令路由 → 业务逻辑 → 持久化
```

### 数据流

```
QQ消息 → 框架/协议层 → 消息处理器
  → 唤醒词匹配（config.json 中的 wake_words）
  → 命令解析（别名 → 内部名，通过 command.json）
  → 权限检查（super_admins + 各配置 permissions.json + command.min_level）
  → 指令路由（/help, /p, /rp, /h, /a, /config）
  → 业务逻辑
  → dm.save_config() 持久化到 data/<配置名>/
```

### 多配置架构

```
配置A（全局默认继承）
  ├── 通知群 ── 接收执行通报
  ├── 执行群1, 执行群2 ── 同步执行处罚
  └── punish/ ── 独立处罚记录 + 黑名单

配置B（覆盖部分命令）
  ├── 通知群（可与 A 重叠）
  ├── 执行群3
  └── punish/ ── 独立处罚记录 + 黑名单
```

- 一个群可属于多个配置
- 各配置处罚记录、黑名单、权限完全独立
- 命令配置未设置时自动继承全局 `data/command.json`
- `/help` 按配置分组显示，标注各配置权限

### 权限模型

| 等级 | 角色 | 配置方式 | 权限 |
| --- | --- | --- | --- |
| 0 | 超级管理员 | 配置文件（`superAdmins` / `super_admins`） | 全部指令 |
| ≥1 | 管理员 | `/a` 指令设置 | 数字越小权限越高，受 `command.json` `min_level` 限制 |
| -1 | 普通成员 | 默认 | 仅 `min_level: -1` 的命令 |

### 数据文件

每个配置独立存储：

| 文件 | 位置 | 内容 |
| --- | --- | --- |
| `groups.json` | 配置根 | 通知群 + 执行群（`ConfigInfo`） |
| `command.json` | 配置根（可选）+ 全局 | 命令启用/名称/权限（`CommandConfig`） |
| `permissions.json` | 配置根 | 权限映射（`Dict[str, int]`） |
| `records.json` | `punish/` | 处罚记录（`PunishRecord`） |
| `blacklist.json` | `punish/` | 黑名单（`BlacklistItem`） |

所有数据文件使用 `.tmp` 原子写入，加载失败时自动尝试 `.tmp` 恢复。

---

## QFun 版开发指南

### 运行环境

| 项 | 说明 |
| --- | --- |
| 引擎 | Modern BeanShell（Java 8+ 语法，**不支持注解**） |
| 宿主 | QFun Plugin for Android QQ |
| 类加载器 | 持有宿主 QQ 和模块的 `classLoader` |
| 线程 | 事件回调在 **IO 线程**；UI 操作需切换主线程 |
| API | 全局函数，无需 import，脚本任意位置直接调用 |

详见 [SDK/QFdocs/QFun_Plugin_API.md](../SDK/QFdocs/QFun_Plugin_API.md)。

### 命名规范

- 类名：`PascalCase`（`ConfigState`、`PunishRecord`）
- 方法名/变量：`camelCase`（`saveAll`、`findGroupByGroupId`）
- 常量：`camelCase`（`wakeWords`、`dataDirPath`）

### BeanShell 类型陷阱

**关键规则：数值从 Map 取出时，始终用 `String.valueOf()` + 包装类型 `parseXxx`，不能直接 cast。**

```java
// ✅ 正确
r.id = Integer.parseInt(String.valueOf(map.get("id")));
r.sender = Long.parseLong(String.valueOf(map.get("sender")));

// ❌ 错误 — bsh.Primitive 转型异常
r.id = (int) map.get("id");
r.sender = (long) map.get("sender");
```

原因：BeanShell 中的数值以 `bsh.Primitive` 形式存在，Java 强制类型转换会失败。

### 空值防护

所有 JSON 反序列化的可选字段需空值保护：

```java
r.reason = map.get("reason") != null ? map.get("reason").toString() : "";
r.content = map.get("content") != null ? map.get("content").toString() : "";
```

### 类命名冲突

避免与 Java 标准库类名冲突。`PunishRecord` 原名 `Record`，与 `java.lang.Record`（Java 14+）冲突，已重命名。

### 线程安全

`onMsg` 和 `joinGroup` 可能在不同线程并发：

```java
List<PunishRecord> records = Collections.synchronizedList(new ArrayList<>());

// 双重检查锁定初始化
if (!initialized) {
    synchronized (initLock) {
        if (!initialized) { init(); initialized = true; }
    }
}
```

### API 调用模式

所有 QFun API 为全局函数，支持属性直接访问：

```java
// 消息属性
String text = msgData.msg;
int type = msgData.type;      // 2=群聊, 1=私聊
String peerUin = msgData.peerUin;

// API 调用 — 全局函数，无需 context
List members = getGroupMemberList(groupCode);
shutUp(groupCode, qq, duration);
kickGroup(groupCode, qq, false);
sendMsg(peerUin, message, 2);
log("info.log", "message");
```

### 添加新指令（QFun）

1. 在 `CommandConfig.defaults()` 中添加命令配置（internal name, names, min_level）
2. 在 `onMsg()` 的 switch 中添加 `case "新内部名":` 分支
3. 实现 `cmdXxx()` 方法
4. 在 `initHelpMaps()` 中的 `CMD_DESC` / `CMD_FORMAT` / `CMD_EXAMPLES` / `CMD_DETAIL` 添加帮助条目

### 添加新数据持久化（QFun）

1. 定义数据模型类（遵循 `toMap()`/`fromMap()` 模式）
2. 添加 `loadConfigXxx(name)` / `saveConfigXxx(name, data)` 方法
3. 在 `saveConfig(name)` 中调用新的保存方法
4. 在 `init()` 的配置加载循环中加载新数据

### 添加新配置项（QFun）

1. 在 `config.properties` 中添加键值
2. 在 `checkAndRepairConfig()` 中添加默认值处理
3. 更新 README

---

## OneBot11 版开发指南

### 运行环境

| 项 | 说明 |
| --- | --- |
| 语言 | Python 3.10+ |
| 异步框架 | `asyncio` + `aiohttp` + `websockets` |
| 数据模型 | Pydantic v2 |
| 图像渲染 | Pillow（可选，可配置关闭） |
| 协议 | OneBot v11（HTTP + WebSocket） |

### 架构分层

```
main.py                    # 入口：加载配置，初始化模块，启动事件循环
  ├── bot/api.py           # 通信层：HTTP/WS API 调用封装
  ├── bot/client.py        # 通信层：WebSocket 连接管理（正向/反向）
  ├── bot/handler.py       # 通信层：事件 → CommandHandler 分发
  └── core/                # 业务层
      ├── commands.py      # 所有指令实现
      ├── models.py        # Pydantic 数据模型 + ConfigState
      ├── data_manager.py  # JSON 持久化
      └── render.py        # Pillow 图片渲染
```

### 入口流程（main.py）

```python
async def main():
    config = load_config()                     # 加载/生成 config.json
    setup_logging(config.log)                  # 按配置重建日志
    api = OneBotAPI(config)                    # 初始化 HTTP API
    dm = DataManager(config.data_dir)          # 初始化数据管理器
    cmd = CommandHandler(api, dm, ...)         # 初始化指令处理器
    cmd.load()                                 # 加载全局 command.json + 各配置数据

    ws = OneBotWS(config, handler)             # 初始化 WebSocket
    await ws.start()                           # 启动 WS
```

### 数据模型（Pydantic）

```python
class ConfigInfo(BaseModel):
    notify_group: Optional[str] = Field(default=None, alias='notifyGroup')
    execution_groups: set[str] = Field(default_factory=set, alias='executionGroups')

    model_config = {"populate_by_name": True}  # 支持驼峰/下划线互转

class PunishRecord(BaseModel):
    id: int
    sender: int
    time: int
    # ... 其他字段

    @model_validator(mode='before')
    @classmethod
    def coerce_int(cls, data):
        """将字符串数字转为 int，兼容 QFun Java 版数据"""
        for field in ('id', 'sender', 'time', 'from_group', 'target'):
            if field in data and isinstance(data[field], str):
                data[field] = int(data[field])
        return data
```

### 原子写入

```python
class DataManager:
    def _atomic_write(self, path: Path, data):
        tmp = path.with_suffix('.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(path)  # 原子重命名

    def _safe_load(self, path: Path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            # 尝试 .tmp 恢复
            tmp = path.with_suffix('.tmp')
            if tmp.exists():
                tmp.rename(path.with_suffix('.bak'))
            # 返回空数据
            return {} if 'permissions' in path.name else []
```

### 添加新指令（OneBot11）

1. 在 `core/commands.py` 的 `handle_message()` 中添加分发分支
2. 实现 `_xxx()` 方法
3. 在 `CommandConfig.defaults()` 中添加命令配置
4. 在 `_CMD_DESC` / `_CMD_FORMAT` / `_CMD_EXAMPLES` / `_CMD_DETAIL` 中添加帮助条目

### 添加新数据持久化（OneBot11）

1. 在 `core/models.py` 中定义 Pydantic 模型
2. 在 `core/data_manager.py` 中添加 `load_config_xxx()` / `save_config_xxx()` 方法
3. 在 `DataManager.save_config()` 中调用新方法

### 添加新配置项（OneBot11）

1. 在 `main.py` 的 `load_config()` 默认值模板中添加字段
2. 在 `main()` 中读取配置段

### 命令配置（command.json）

全局 `data/command.json` 定义默认命令行为。各配置覆盖项写入 `data/<配置>/command.json`。

```json
{
  "commands": {
    "punish_do": {
      "enabled": true,
      "names": ["p", "punish"],
      "min_level": 1
    }
  }
}
```

`names` 支持多个命令名指向同一功能；`min_level` 控制所需最低权限等级；`sub` 支持递归子命令配置。

### WS Universal 协议

正向 WS Universal 模式下，API 调用和事件推送共用一条连接：

```python
# 发送 API 调用（带 echo 追踪）
echo_id = str(uuid.uuid4())
await ws.send(json.dumps({"action": "get_group_member_list", "params": {...}, "echo": echo_id}))

# 等待响应（通过 asyncio.Future）
future = asyncio.get_event_loop().create_future()
self._pending[echo_id] = future
result = await asyncio.wait_for(future, timeout=30)
```

---

## CI / 发布流程

发布通过 Git tag 触发（`.github/workflows/release.yml`）：

1. 推送 `v*` 格式的 tag（如 `v1.0.5`）
2. CI 自动构建两个发行包：
   - `HollowGroupManager_QFun-<version>.zip` — QFun 版（`main.java` + `config.properties` + `info.prop` + `desc.txt` + `README.md`）
   - `HollowGroupManager_OneBot11-<version>.zip` — OneBot11 版（`main.py` + `requirements.txt` + `README.md` + `LICENSE` + `bot/` + `core/`）
3. 从各版 `history.txt` 提取更新日志，组合 git-cliff changelog
4. 创建 GitHub Release

版本号含 `alpha`/`beta`/`rc`/`dev`/`preview` 时自动标记为预发布。

---

## 测试

目前两版均无自动化测试。主要验证手段：

- **QFun 版**：在 Android 模拟器或真机上加载插件，通过群聊验证功能
- **OneBot11 版**：本地运行，配合 NapCat/LLOneBot 测试

## 相关文档

- [版本详细对比](comparison.md)
- [QFun 版 README](../QFun/README.md)
- [OneBot11 版 README](../OneBot11/README.md)
