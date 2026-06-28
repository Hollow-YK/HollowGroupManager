# 多群联动管理Bot — OneBot11 版

基于 **[OneBot v11 标准协议](https://github.com/botuniverse/onebot-11)** 的多群联动管理 Bot。纯 Python 实现，不依赖任何 Bot 框架，支持 HTTP / WebSocket 多种通信模式。

> 本项目另提供 [QFun 版](../QFun/README.md)，基于 QFun Plugin 框架直接在 Android QQ 内运行。1.0.5 及以前两版功能等价、数据格式兼容；1.0.6 起 QFun 版更新将放缓。
>
> 📖 [详细对比](../doc/comparison.md) · [开发文档](../doc/development/OneBot11/) · [项目总览](../README.md)

## 快速开始

### 1. 前置要求

- Python 3.10+
- 任意 **OneBot v11 实现**

### 2. 安装

```bash
cd HollowGroupManager
python -m venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

> 也可使用 [uv](https://github.com/astral-sh/uv)：`uv venv && uv pip install -r requirements.txt`

### 3. 配置

首次运行自动生成 `config.json`：

```bash
python main.py
```

编辑生成的 `config.json`：

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
| `onebot.mode` | 通信模式（见下方） |
| `onebot.http_url` | HTTP API 地址，`""` 禁用 |
| `onebot.ws_url` | 正向 WS 地址，`""` 禁用 |
| `onebot.ws_reverse_port` | 反向 WS 端口，`0` 禁用 |
| `onebot.access_token` | 鉴权令牌，需与 OneBot 实现一致 |
| `plugin.wake_words` | 唤醒前缀列表 |
| `plugin.super_admins` | 超管 QQ 列表（必须配置） |
| `plugin.data_dir` | 数据目录 |
| `render.enabled` | 图片渲染开关（Pillow ~5MB，可关闭降级为纯文本） |
| `log.log_to_file` | 是否输出日志到文件（`true` / `false`） |
| `log.log_level` | 日志等级：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `log.log_dir` | 日志目录，默认 `logs`，每次启动生成 `YYYY-MM-DD_HH-MM-SS.log` |

### 4. 通信模式

通过 `onebot.mode` 选择：

| 模式 | `mode` 值 | API 通道 | 事件通道 | 适用场景 |
| --- | --- | --- | --- | --- |
| HTTP + 正向 WS | `http_ws` | HTTP POST | 正向 WS（Bot 连 OneBot） | 本地开发（默认） |
| 正向 WS Universal | `ws` | WS | WS（同一连接） | 单端口部署 |
| 反向 WS Universal | `ws_reverse` | WS | 反向 WS（OneBot 连 Bot） | 内网穿透 |
| HTTP + 反向 WS | `http_ws_reverse` | HTTP POST | 反向 WS | Bot 有公网 IP |

> 四种模式任选其一。详细架构图见 [doc/comparison.md](../doc/comparison.md#onebot11-通信模式)。

### 5. 启动

```bash
python main.py
```

在目标群发送 `/config new 配置名称` 创建配置，`/help` 查看所有指令。

## 指令参考

> `[唤醒词]` 为 `plugin.wake_words` 中配置的前缀（默认 `/`、`!`、`。`）。`QQ用户` 支持 @某人 或 QQ 号。命令名可通过 `command.json` 自定义（如 `/punish` 别名 `/p`）。

| 指令 | 默认权限 | 格式 | 说明 |
| --- | --- | --- | --- |
| `/help` | -1 | `[唤醒词]help [命令]` | 按配置分组显示可用指令 |
| `/config` | 0 | `[唤醒词]config <子命令>` | 配置管理：new / rename / notify / set / remove / group / list |
| `/admin` | 0 | `[唤醒词]admin [配置] <QQ用户> [等级]` | 设权限等级（-1=普通，≥1 数字越大越低） |
| `/punish` | 1 | `[唤醒词]punish [配置] <QQ用户> <方式> [内容] <原因>` | 处罚：`kick [f]` / `mute 时长` / `warn` |
| `/revokepunish` | 1 | `[唤醒词]revokepunish [配置] <记录ID> [撤销原因]` | 撤销处罚（多配置群必填配置名） |
| `/history` | 1 | `[唤醒词]history [配置] [QQ用户] [-i]` | 查询：无参=表格 / 有参=汇总 / `-i`=详情 |
| `/verify` | 0 | `[唤醒词]verify <子命令>` | 进群答题验证：on / off / status / config / block / question |
| `/approval` | 0 | `[唤醒词]approval <子命令>` | 加群审批：on / off / status / config |

禁言时长：纯数字=天，支持 `1d2h30m`、`3h`、`30m` 等组合格式。各命令的启用、名称、权限要求可在 `data/command.json`（全局）和各配置的 `command.json` 中自定义。

### 处罚示例

```text
/punish @某人 mute 1d2h 广告刷屏     → 禁言 1 天 2 小时
/punish 123456 kick f 严重违规        → 踢出并加入黑名单
/punish @某人 warn 注意言辞           → 警告
/punish 反馈组 @某人 mute 1d 测试     → 在指定配置中执行
```

## 权限等级

| 等级 | 角色 | 配置方式 | 权限 |
| --- | --- | --- | --- |
| 0 | 超级管理员 | `config.json` → `super_admins` | 全部指令 |
| ≥1 | 管理员 | `/admin` 指令设置 | 数字越小权限越高（受 `command.json` 中 `min_level` 限制） |
| -1 | 普通成员 | 默认 | 仅 `min_level: -1` 的命令 |

## 文件结构

```text
OneBot11/
├── main.py              # 入口（asyncio）+ 模块装配注册
├── config.json          # 配置文件
├── requirements.txt     # Python 依赖
├── README.md            # 本文档
├── history.txt          # 版本历史
├── LICENSE              # AGPLv3
├── bot/                 # [框架] 通信层 — 协议实现，功能模块不可见
│   ├── api.py           #   HTTP/WS API 封装
│   ├── client.py        #   WebSocket 客户端/服务端
│   └── handler.py       #   原始事件 → dispatcher 桥接
├── core/                # [框架] 基础设施 — 功能模块的唯一依赖入口
│   ├── models.py        #   Pydantic 数据模型
│   ├── data_manager.py  #   JSON 持久化（多配置 + .tmp 原子写）
│   └── dispatcher.py    #   指令/事件注册 + 统一 Bot 能力 API + 分发核心
├── features/            # [功能] 所有业务功能
│   ├── render.py        #   图片渲染（Pillow）
│   ├── basic/           #   [基础功能]
│   │   ├── help.py      #   /help 指令
│   │   ├── config_cmd.py#   /config 多配置管理
│   │   └── admin.py     #   /admin 权限管理
│   ├── punish/          #   [处罚系统]
│   │   ├── punish.py    #   /punish 处罚 + 黑名单入群监听
│   │   ├── rp.py        #   /revokepunish 撤销处罚
│   │   └── history.py   #   /history 查询记录
│   └── verify/          #   [进群验证]（v1.0.6 新增）
│       ├── __init__.py
│       ├── models.py    #   数据模型（验证方案 / 审批方案）
│       ├── verification.py  #   答题验证（多模式出题 + 答案匹配）
│       └── approval.py  #   加群审批（正则匹配入群申请）
├── tools/               # 独立工具
│   └── migrate.py       # 旧版数据迁移脚本
├── data/                # 运行时数据
│   ├── command.json     # 全局命令配置（默认值）
│   └── <配置名>/         # 各配置独立目录
│       ├── groups.json          # 通知群 + 执行群
│       ├── command.json         # 命令覆盖（可选）
│       ├── permissions.json     # 权限映射
│       ├── punish/              # 处罚子系统
│       │   ├── records.json     # 处罚记录
│       │   └── blacklist.json   # 黑名单
│       └── verify/                      # 进群验证子系统
│           ├── verify.json           # 验证方案
│           ├── approval.json         # 审批方案
│           ├── verify_groups.json    # 群验证开关
│           └── approval_groups.json  # 群审批开关
└── logs/                # 日志文件（时间命名）
```

### 架构概览

```
功能模块（features/）    ← 只依赖 dispatcher，不直接引用 bot/
        │
        ▼
core/dispatcher.py      ← 注册接口 + Bot 能力 API + 权限/配置/数据服务
        │
        ▼
bot/ (api.py, client.py) ← OneBot v11 协议封装（对功能模块透明）
```

功能模块通过 `dispatcher.register_command()` / `register_event()` 注册，无需修改框架代码。Dispatcher 提供统一的 `send_message()` / `kick()` / `ban()` 等语义化 API 封装底层协议细节。

## 配置系统

### 全局命令配置 (`data/command.json`)

自动生成，定义所有命令的默认行为。各配置目录下的 `command.json` 可覆盖特定命令（未覆盖项自动继承全局）。

### 多配置架构

每个配置独立管理：通知群、执行群、权限、处罚记录、黑名单。一个群可属于多个配置。`/help` 按配置分组显示可用指令。

## 数据兼容

采用 `.tmp` 原子写入防止数据损坏，加载失败时自动尝试 `.tmp` 恢复。旧版扁平数据可通过 `python tools/migrate.py` 迁移至多配置架构。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [doc/comparison.md](../doc/comparison.md) | QFun vs OneBot11 详细对比（通信模式架构图等） |
| [doc/development/OneBot11/](../doc/development/OneBot11/) | 开发指南（框架、功能、数据开发） |
| [QFun/AGENTS.md](../QFun/AGENTS.md) | QFun 版开发提示（BeanShell 注意事项） |
| [根目录 README](../README.md) | 项目总览 |

## 许可证

GNU Affero General Public License v3.0 — 详见 [LICENSE](LICENSE)。

Copyright (C) 2026 Hollow-YK
