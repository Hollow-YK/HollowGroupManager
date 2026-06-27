# OneBot11 版开发指南 — 概述

本目录包含 OneBot11 版的开发文档，按主题拆分：

| 文档 | 内容 |
| --- | --- |
| [framework.md](framework.md) | 框架开发（bot/ 通信层、core/dispatcher、WS 协议、入口流程） |
| [features.md](features.md) | 功能开发（注册指令/事件、模块模式、添加新指令、command.json） |
| [data.md](data.md) | 数据开发（Pydantic 模型、DataManager、原子写入、config.json） |

## 运行环境

| 项 | 说明 |
| --- | --- |
| 语言 | Python 3.10+ |
| 异步框架 | `asyncio` + `aiohttp` + `websockets` |
| 数据模型 | Pydantic v2 |
| 图像渲染 | Pillow（可选，可配置关闭） |
| 协议 | OneBot v11（HTTP + WebSocket） |

## 架构分层

```
main.py                    # 入口：加载配置，初始化 dispatcher，注册功能模块
  ├── bot/api.py           # [框架] HTTP/WS API 调用封装
  ├── bot/client.py        # [框架] WebSocket 连接管理（正向/反向）
  ├── bot/handler.py       # [框架] 原始事件 → dispatcher 桥接
  ├── core/                # [框架] 基础设施
  │   ├── dispatcher.py   #   注册接口 + 统一 API + 分发核心
  │   ├── models.py        #   Pydantic 数据模型 + ConfigState
  │   └── data_manager.py  #   JSON 持久化
  └── features/            # [功能] 业务功能（只依赖 dispatcher）
      ├── render.py        #   Pillow 图片渲染
      ├── basic/           #   基础功能
      │   ├── help.py      #   /help
      │   ├── config_cmd.py#   /config
      │   └── admin.py     #   /a
      ├── punish/          #   punish功能
      │   ├── punish.py    #   /punish + 黑名单入群监听
      │   ├── rp.py        #   /revokepunish
      │   └── history.py   #   /history
      └── verify/          #   进群验证
          ├── verification.py  #   答题验证
          └── approval.py  #   加群审批
```

三层分离：

1. **`bot/`** — 通信层，封装 OneBot v11 协议细节，对功能模块透明
2. **`core/`** — 基础设施，提供 `CommandDispatcher` 作为功能模块的唯一依赖入口
3. **`features/`** — 业务功能，通过 dispatcher 注册指令和事件，不直接引用 `bot/`
   - basic/：基础功能（help、config、admin）
   - punish/：处罚系统（punish、rp、history）
   - verify/：进群验证（答题验证 + 加群审批）

功能模块通过 `dispatcher.register_command()` / `register_event()` 注册，无需修改框架代码。Dispatcher 提供统一的 `send_message()` / `kick()` / `ban()` 等语义化 API 封装底层协议细节。

## 通信模式

OneBot11 版支持四种通信模式，通过 `config.json` 的 `onebot.mode` 选择：

| 模式 | `mode` 值 | API 通道 | 事件通道 |
| --- | --- | --- | --- |
| HTTP + 正向 WS | `http_ws` | HTTP POST | 正向 WS（Bot 连 OneBot） |
| 正向 WS Universal | `ws` | WS | WS（同一连接） |
| 反向 WS Universal | `ws_reverse` | WS | 反向 WS（OneBot 连 Bot） |
| HTTP + 反向 WS | `http_ws_reverse` | HTTP POST | 反向 WS |

## 相关文档

| 文档 | 内容 |
| --- | --- |
| [../index.md](../index.md) | 共享架构、配置管理、CI/发布 |
| [../../comparison.md](../../comparison.md) | QFun vs OneBot11 详细对比 |
| [../../../OneBot11/README.md](../../../OneBot11/README.md) | OneBot11 版用户文档 |
