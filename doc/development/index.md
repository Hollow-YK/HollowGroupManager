# 开发文档 — 共享架构

本文档涵盖 HollowGroupManager 两个版本共享的架构设计、配置管理和发布流程。各版本专属开发指南见子目录。

## 项目结构

```text
HollowGroupManager/
├── QFun/                          # QFun 插件版（Java/BeanShell）
│   ├── main.java                  # 单文件插件脚本
│   ├── config.properties          # 唤醒词、超管、数据目录
│   ├── info.prop                  # 插件元信息（id/名称/版本/作者）
│   ├── desc.txt                   # 插件描述（QFun 列表展示）
│   ├── README.md                  # 用户文档
│   ├── AGENTS.md                  # QFun 专属开发文档（AI 开发用）
│   ├── history.txt                # 版本历史
│   ├── LICENSE                    # AGPLv3
│   └── data/                      # 运行时数据（自动生成）
├── OneBot11/                      # OneBot v11 版（Python）
│   ├── main.py                    # 入口（asyncio）+ 模块装配注册
│   ├── config.json                # 配置文件
│   ├── requirements.txt           # Python 依赖
│   ├── README.md                  # 用户文档
│   ├── history.txt                # 版本历史
│   ├── LICENSE                    # AGPLv3
│   ├── bot/                       # [框架] 通信层 — 协议实现
│   │   ├── api.py                 #   HTTP/WS API 封装
│   │   ├── client.py              #   WebSocket 客户端/服务端
│   │   └── handler.py             #   原始事件 → dispatcher 桥接
│   ├── core/                      # [框架] 基础设施 — 功能模块唯一依赖
│   │   ├── models.py              #   Pydantic 数据模型
│   │   ├── data_manager.py        #   JSON 持久化
│   │   └── dispatcher.py          #   注册接口 + 统一 API + 分发核心
│   ├── features/                  # [功能] 所有业务功能
│   │   ├── render.py              #   图片渲染（Pillow）
│   │   ├── basic/                 #   [基础功能]
│   │   │   ├── help.py            #   /help 指令
│   │   │   ├── config_cmd.py      #   /config 多配置管理
│   │   │   └── admin.py           #   /admin 权限管理
│   │   ├── punish/                #   [处罚系统]
│   │   │   ├── punish.py          #   /punish 处罚 + 黑名单入群监听
│   │   │   ├── rp.py              #   /revokepunish 撤销处罚
│   │   │   └── history.py         #   /history 查询记录
│   │   └── verify/                #   [进群验证]
│   │       ├── verification.py    #   答题验证
│   │       └── approval.py        #   加群审批
│   ├── tools/                     # 独立工具
│   │   └── migrate.py             # 旧版数据迁移
│   ├── debug/                     # 调试工具（模拟事件注入）
│   │   ├── __init__.py            # DebugManager + DebugAPI 核心引擎
│   │   ├── cli.py                 # CLI 交互式 REPL
│   │   ├── http_server.py         # HTTP 调试端点
│   │   ├── runner.py              # JSON 批量测试运行器
│   │   └── examples/              # 示例测试文件
│   ├── data/                      # 运行时数据
│   │   ├── command.json           # 全局命令配置
│   │   └── <配置名>/              # 各配置独立目录
│   │       ├── groups.json        # 通知群 + 执行群
│   │       ├── command.json       # 命令覆盖（可选）
│   │       ├── permissions.json   # 权限映射
│   │       ├── punish/            # 处罚子系统
│   │       │   ├── records.json
│   │       │   └── blacklist.json
│   │       └── verify/                      # 进群验证子系统
│   │           ├── verify.json           # 验证方案
│   │           ├── approval.json         # 加群审批方案
│   │           ├── verify_groups.json    # 群验证开关
│   │           └── approval_groups.json  # 群审批开关
│   └── logs/                      # 日志文件（时间命名）
├── doc/                           # 项目文档
│   ├── comparison.md              # 两版详细对比
│   └── development/               # 开发文档（本目录）
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
  → 唤醒词匹配（config 中的 wake_words）
  → 命令解析（别名 → 内部名，通过 command.json）
  → 权限检查（super_admins + 各配置 permissions.json + command.min_level）
  → 指令路由（/help, /config, /admin, /punish, /revokepunish, /history, /verify, /approval）
  → 业务逻辑
  → 持久化到 data/<配置名>/
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
| ≥1 | 管理员 | `/admin` 指令设置 | 数字越小权限越高，受 `command.json` `min_level` 限制 |
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
| `verify/verify.json` | `verify/` | 进群答题验证方案 |
| `verify/approval.json` | `verify/` | 加群审批方案 |
| `verify/verify_groups.json` | `verify/` | 群验证开关 |
| `verify/approval_groups.json` | `verify/` | 群审批开关 |

所有数据文件使用 `.tmp` 原子写入，加载失败时自动尝试 `.tmp` 恢复。

## 配置文件管理

### command.json — 命令配置

全局 `data/command.json` 定义所有命令的默认行为。各配置目录下的 `command.json` 可覆盖特定命令（未覆盖项自动继承全局）。

```json
{
  "commands": {
    "punish_do": {
      "enabled": true,
      "names": ["punish", "p"],
      "min_level": 1
    },
    "config": {
      "enabled": true,
      "names": ["config"],
      "min_level": 0,
      "sub": {
        "new":    { "enabled": true },
        "rename": { "enabled": true },
        "notify": { "enabled": true },
        "set":    { "enabled": true },
        "remove": { "enabled": true },
        "group":  { "enabled": true, "min_level": -1 }
      }
    }
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `enabled` | `bool` | 是否启用该命令 |
| `names` | `list[str]` | 外部命令名列表（如 `["punish", "p"]`），第一个为主名 |
| `min_level` | `int?` | 最低权限等级。`null`=继承上级，`-1`=所有人，`0`=超管，`≥1`=管理员（越小权限越高） |
| `sub` | `dict?` | 子命令配置（递归结构），如 `/config new` |

**继承规则**：`min_level` 为 `null` 时向上继承。子命令的 `min_level` 继承父命令。配置级覆盖优先于全局。

### 配置文件对比

| 维度 | QFun 版 | OneBot11 版 |
| --- | --- | --- |
| 格式 | `config.properties`（Java Properties） | `config.json`（JSON） |
| 超管配置 | `superAdmins=12345,10000` | `"super_admins": ["123456789"]` |
| 唤醒词 | `wakeWords=/,!,。` | `"wake_words": ["/", "!", "。"]` |
| 数据目录 | `dataDir=data` | `"data_dir": "data"` |
| 额外配置段 | 无 | `onebot`（通信）、`render`（渲染开关）、`log`（日志） |

## CI / 发布流程

发布通过 Git tag 触发（`.github/workflows/release.yml`）：

1. 推送 `v*` 格式的 tag（如 `v1.0.5`）
2. CI 自动构建两个发行包：
   - `HollowGroupManager_QFun-<version>.zip` — QFun 版（`main.java` + `config.properties` + `info.prop` + `desc.txt` + `README.md`）
   - `HollowGroupManager_OneBot11-<version>.zip` — OneBot11 版（`main.py` + `requirements.txt` + `README.md` + `LICENSE` + `bot/` + `core/` + `features/`）
3. 从各版 `history.txt` 提取更新日志，组合 git-cliff changelog
4. 创建 GitHub Release

版本号含 `alpha`/`beta`/`rc`/`dev`/`preview` 时自动标记为预发布。

## 测试

目前两版均无自动化测试。主要验证手段：

- **QFun 版**：在 Android 模拟器或真机上加载插件，通过群聊验证功能
- **OneBot11 版**：本地运行，配合 NapCat/LLOneBot 测试

## 版本专属文档

| 文档 | 内容 |
| --- | --- |
| [OneBot11/](OneBot11/) | OneBot11 版开发指南（框架、功能、数据） |
| [QFun/](QFun/) | QFun 版开发指南 + 开发注意事项 |
| [../comparison.md](../comparison.md) | QFun vs OneBot11 详细对比 |
| [../../QFun/AGENTS.md](../../QFun/AGENTS.md) | QFun 版 AI 开发提示（BeanShell 约定等） |
