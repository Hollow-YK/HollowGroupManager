# 多群联动管理Bot — OneBot11 版

基于 **[OneBot v11 标准协议](https://github.com/botuniverse/onebot-11)** 的多群联动管理 Bot。纯 Python 实现，不依赖任何 Bot 框架，支持 HTTP / WebSocket 多种通信模式。

> 本项目另提供 [QFun 版](../QFun/README.md)，基于 QFun Plugin 框架直接在 Android QQ 内运行。两版功能等价、数据格式兼容。
>
> 📖 [详细对比](../doc/comparison.md) · [开发文档](../doc/development.md) · [项目总览](../README.md)

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

在目标群发送 `/group admin 管理组名称` 创建管理组，`/help` 查看所有指令。

## 指令参考

> `[唤醒词]` 为 `plugin.wake_words` 中配置的前缀（默认 `/`、`!`、`。`）。`QQ用户` 支持 @某人 或 QQ 号。

| 指令 | 权限 | 格式 | 说明 |
| --- | --- | --- | --- |
| `/help` | 0 / 1 | `[唤醒词]help [命令]` | 指令列表或命令详情 |
| `/p` | 0 / 1 | `[唤醒词]p <QQ用户> <方式> [内容] <原因>` | 处罚：`kick [f]` / `mute 时长` / `warn` |
| `/h` | 0 / 1 | `[唤醒词]h [QQ用户] [-i]` | 查询：无参=全部表格 / 有参=汇总 / `-i`=详情表格 |
| `/rp` | 0 / 1 | `[唤醒词]rp <记录ID> [撤销原因]` | 撤销处罚（禁言自动解禁，踢黑移出黑名单） |
| `/a` | 0 | `[唤醒词]a <QQ用户> [1/-1]` | 设管理员（1）或降级（-1）；超管只能在配置文件中设定 |
| `/group` | 0 | `[唤醒词]group <admin\|set\|remove\|info>` | 管理组配置 |

禁言时长：纯数字=天，支持 `1d2h30m`、`3h`、`30m` 等组合格式。

### 处罚示例

```text
/p @某人 mute 1d2h 广告刷屏     → 禁言 1 天 2 小时
/p 123456 kick f 严重违规        → 踢出并加入黑名单
/p @某人 warn 注意言辞           → 警告
```

## 权限等级

| 等级 | 角色 | 配置方式 | 权限 |
| --- | --- | --- | --- |
| 0 | 超级管理员 | `config.json` → `super_admins` | 全部指令 |
| 1 | 管理员 | `/a` 指令设置 | 处罚、查询、撤销 |
| -1 | 普通成员 | 默认 | 不响应指令 |

## 文件结构

```text
OneBot11/
├── main.py              # 入口（asyncio）
├── config.json          # 配置文件
├── requirements.txt     # Python 依赖
├── README.md            # 本文档
├── history.txt          # 版本历史
├── LICENSE              # AGPLv3
├── bot/                 # 通信层
│   ├── api.py           # HTTP/WS API 封装
│   ├── client.py        # WebSocket 客户端
│   └── handler.py       # 事件分发
├── core/                # 业务逻辑
│   ├── models.py        # Pydantic 数据模型
│   ├── data_manager.py  # JSON 持久化（.tmp 原子写）
│   ├── commands.py      # 指令实现
│   └── render.py        # 图片生成（Pillow）
└── data/                # 运行时数据
    ├── groups.json
    ├── records.json
    ├── permissions.json
    └── blacklist.json
```

## 数据兼容

数据格式与 QFun Java 原版兼容，可互换 JSON 文件。采用 `.tmp` 原子写入防止数据损坏，加载失败时自动尝试 `.tmp` 恢复。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [doc/comparison.md](../doc/comparison.md) | QFun vs OneBot11 详细对比（通信模式架构图等） |
| [doc/development.md](../doc/development.md) | 开发指南（架构、添加指令、数据持久化等） |
| [QFun/AGENTS.md](../QFun/AGENTS.md) | QFun 版开发提示（BeanShell 注意事项） |
| [根目录 README](../README.md) | 项目总览 |

## 许可证

GNU Affero General Public License v3.0 — 详见 [LICENSE](LICENSE)。

Copyright (C) 2026 Hollow-YK
