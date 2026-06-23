# HollowGroupManager

基于 **[OneBot v11 标准协议](https://github.com/botuniverse/onebot-11)** 的多群联动管理 Bot。纯 Python 实现，不依赖任何 Bot 框架。

## 通信模式

通过 `config.json` 中 `onebot.mode` 字段选择。四种模式**各自独立**，任选其一即可。

### `"http_ws"` — HTTP API + 正向 WS 事件（默认）

```
  OneBot (服务端)                      HollowGroupManager (客户端)
  ┌─────────────────┐                 ┌──────────────────────────┐
  │ HTTP :3000      │◄─── POST ──────│ api.py    (主动调用 API)  │
  │ WS :3001        │── 推送事件 ──→│ client.py (主动连过去)     │
  └─────────────────┘                 └──────────────────────────┘
```
- OneBot 开 HTTP + WS，Bot 去连
- API 走 HTTP，事件走 WS，各司其职

### `"ws"` — 正向 WS Universal（单连接，无需 HTTP）

```
  OneBot (服务端)                      HollowGroupManager (客户端)
  ┌─────────────────┐                 ┌──────────────────────────┐
  │ WS :3001  /     │◄═ 双向 JSON ═►│ client.py                │
  │                 │  事件 ←  → API │ (一条连接搞定一切)         │
  └─────────────────┘                 └──────────────────────────┘
```
- 仅需 OneBot 开 WS，HTTP 端口可关
- API 调用和事件推送在同一连接上

### `"ws_reverse"` — 反向 WS Universal（Bot 监听）

```
  OneBot (客户端)                      HollowGroupManager (服务端)
  ┌─────────────────┐                 ┌──────────────────────────┐
  │ WS 客户端        │── 连接 ──────→│ WS :8080   (Bot 监听)     │
  │                 │◄═ 双向 JSON ═►│ API + 事件 一条连接        │
  └─────────────────┘                 └──────────────────────────┘
```
- Bot 开 WS 服务，OneBot 连过来
- 无需 HTTP，API 和事件全走反向 WS
- OneBot 需配置反向 WS URL 指向 Bot

### `"http_ws_reverse"` — HTTP API + 反向 WS 事件

```
  OneBot (客户端)                      HollowGroupManager (服务端)
  ┌─────────────────┐                 ┌──────────────────────────┐
  │ HTTP :3000      │◄─── POST ──────│ api.py    (主动调用 API)  │
  │ WS 客户端        │── 推送事件 ──→│ WS :8080   (Bot 监听)     │
  └─────────────────┘                 └──────────────────────────┘
```
- API 走 HTTP，事件走反向 WS
- 适合内网穿透场景（Bot 有公网 IP）

### 配置示例

```json
{
  "onebot": {
    "mode": "http_ws",
    "http_url": "http://127.0.0.1:3000",
    "ws_url": "ws://127.0.0.1:3001",
    "ws_reverse_port": 8080,
    "access_token": ""
  }
}
```

| 模式 | `mode` 值 | 需要填的字段 | OneBot 需要开启 |
|---|---|---|---|
| HTTP + 正向 WS | `"http_ws"` | `http_url` + `ws_url` | HTTP + 正向 WS |
| 正向 WS Universal | `"ws"` | `ws_url` | 正向 WS (/ 路径) |
| 反向 WS Universal | `"ws_reverse"` | `ws_reverse_port` | 反向 WS |
| HTTP + 反向 WS | `"http_ws_reverse"` | `http_url` + `ws_reverse_port` | HTTP + 反向 WS |

### 技术栈

| 依赖 | 用途 |
|---|---|
| `aiohttp` | OneBot HTTP API 调用 |
| `websockets` | OneBot WebSocket 事件接收 |
| `pydantic` | 数据模型、序列化、校验 |
| `Pillow` | 图片生成（帮助图、记录表格，~5MB） |

## 快速开始

### 1. 前置要求

- Python 3.10+
- 任意 **OneBot v11 实现**（[NapCat](https://github.com/NapNeko/NapCatQQ)、[LLOneBot](https://github.com/LLOneBot/LLOneBot)、[Lagrange](https://github.com/LagrangeDev/Lagrange.Core)、[OpenShamrock](https://github.com/whitechi73/OpenShamrock) 等）
- 根据选择的通信模式，在 OneBot 实现中开启对应服务：
  - **模式 A**（推荐）：开启 HTTP 服务 + 正向 WS 服务
  - **模式 B**：开启正向 WS 服务（/ 路径）
  - **模式 C**：开启 HTTP 服务 + 反向 WS（配置 OneBot 连接到本 Bot 的 WS 端口）

### 2. 安装（可选 uv 或 pip）

**方式 A：使用 uv（推荐）**

```bash
cd OneBot/HollowGroupManager
uv venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
uv pip install -r requirements.txt
```

**方式 B：使用 pip**

```bash
cd OneBot/HollowGroupManager
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

> 图片渲染使用 Pillow（~5MB），无需额外安装浏览器或字体。若仍想用纯文本，可在 `config.json` 中设 `render.enabled: false`。

### 3. 配置

首次运行自动生成 `config.json`：

```bash
python main.py
```

编辑生成的 `config.json`：

```json
{
  "onebot": {
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
|---|---|
| `http_url` | OneBot HTTP API 地址，`""` = 禁用 HTTP |
| `ws_url` | 正向 WS 地址（Bot 连接 OneBot），`""` = 禁用 |
| `ws_reverse_port` | 反向 WS 端口（Bot 监听，OneBot 连接），`0` = 禁用 |
| `access_token` | 鉴权令牌，需与 OneBot 实现一致 |

> **典型配置**：
> - 默认（模式 A）：`http_url` + `ws_url` 都填
> - 单连接（模式 B）：只填 `ws_url`，`http_url` 留空
> - 反向连接（模式 C）：填 `http_url` + `ws_reverse_port`，`ws_url` 留空
>
> `super_admins` 必须配置，否则无法使用任何指令。

### 4. 启动

```bash
python main.py
```

## 指令列表

以下用首个唤醒词（默认 `/`）展示，实际支持配置中的所有唤醒词。

| 指令 | 权限 | 说明 |
|---|---|---|
| `/help [命令]` | 任意 | 帮助概览或命令详情 |
| `/p <目标> <方式> [内容] <原因>` | 0/1 | 处罚成员 |
| `/rp <记录ID> [撤销原因]` | 0/1 | 撤销处罚 |
| `/h [目标] [-i]` | 0/1 | 查询记录 |
| `/a <目标> [1/-1]` | 0 | 权限管理（仅超管） |
| `/group <子命令>` | 0 | 管理组配置（仅超管） |

### `/p` — 处罚

```
/p @某人 mute 1d2h 广告刷屏
/p 123456 kick f 严重违规        ← f = 加入黑名单
/p @某人 warn 注意言辞
```

**方式**: `kick` / `mute` / `warn`
**时长**: 纯数字=天, `1d2h30m`, `3h`, `30m`

### `/rp` — 撤销

```
/rp 5
/rp 5 误判，实际未违规
```

### `/h` — 查询

```
/h              → 全部记录表格（图片）
/h @某人         → 成员汇总统计（文字）
/h 123456 -i    → 成员详细记录（图片）
```

### `/a` — 权限（仅超管）

```
/a @某人        → 设为管理员
/a 123456 -1    → 降为普通成员
```

### `/group` — 管理组（仅超管）

```
/group admin 反馈组    → 创建管理组（当前群=管理群）
/group set 反馈组      → 加入为执行群
/group info            → 查看信息
/group remove          → 移出
```

## 管理组概念

```
管理组 "反馈组"
├── 管理群 10001     ← 发指令的地方，接收执行通知
├── 执行群 10002     ← 处罚自动同步
├── 执行群 10003
└── 执行群 10004
```

- 任意管理组内的群中发指令，处罚遍历所有执行群
- 一个群只能属于一个管理组

## 帮助内容自定义

帮助文本在 `core/commands.py` 的 `_build_overview_lines` 和 `_build_detail_lines` 方法中定义。使用 `{w}` 占位符表示唤醒词。修改后重启即可生效。

## 文件结构

```
OneBot/HollowGroupManager/
├── main.py                      # 入口
├── config.json                  # 配置文件
├── requirements.txt
├── bot/
│   ├── api.py                   # OneBot v11 HTTP API 封装
│   ├── client.py                # WebSocket 事件客户端
│   └── handler.py               # 事件 → 指令分发
├── core/
│   ├── models.py                # 数据模型 (pydantic)
│   ├── data_manager.py          # JSON 持久化 (.tmp 原子写)
│   ├── commands.py              # 所有指令实现
│   └── render.py                # 图片生成 (Pillow)
└── data/                        # 运行时数据
    ├── groups.json
    ├── records.json
    ├── permissions.json
    └── blacklist.json
```

## 数据持久化

- `.tmp` 原子写入，防止写入过程中断电导致数据损坏
- 加载失败时自动尝试 `.tmp` 恢复
- 数据格式与 QFun Java 原版兼容

## OneBot v11 协议参考

本 Bot 使用的 OneBot v11 接口：

| 功能 | API / 事件 | 文档 |
|---|---|---|
| 发送群消息 | `send_group_msg` | [api/public.md#send_group_msg](https://github.com/botuniverse/onebot-11/blob/master/api/public.md#send_group_msg-发送群消息) |
| 踢出成员 | `set_group_kick` | [api/public.md#set_group_kick](https://github.com/botuniverse/onebot-11/blob/master/api/public.md#set_group_kick-群组踢人) |
| 禁言成员 | `set_group_ban` | [api/public.md#set_group_ban](https://github.com/botuniverse/onebot-11/blob/master/api/public.md#set_group_ban-群组单人禁言) |
| 获取成员列表 | `get_group_member_list` | [api/public.md#get_group_member_list](https://github.com/botuniverse/onebot-11/blob/master/api/public.md#get_group_member_list-获取群成员列表) |
| 接收消息 | `message.group` 事件 | [event/message.md](https://github.com/botuniverse/onebot-11/blob/master/event/message.md) |
| 接收入群通知 | `notice.group_increase` 事件 | [event/notice.md#群成员增加](https://github.com/botuniverse/onebot-11/blob/master/event/notice.md#群成员增加) |
| 鉴权 | `Authorization: Bearer <token>` | [communication/authorization.md](https://github.com/botuniverse/onebot-11/blob/master/communication/authorization.md) |

## 许可证

GNU AGPL v3 — Copyright (C) 2026 Hollow-YK
