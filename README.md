# HollowGroupManager

多群联动管理 Bot — 支持将多个 QQ 群组成管理组，实现跨群同步处罚、记录共享与黑名单联动。

## QFun 版 vs OneBot11 版

本项目提供**两套独立实现**，功能等价，适配不同运行环境：

| 维度 | [QFun 版](QFun/) | [OneBot11 版](OneBot11/) |
| --- | --- | --- |
| **运行平台** | Android（QFun 插件） | 任意平台（Linux / Windows / macOS） |
| **语言** | Java / BeanShell | Python 3.10+ |
| **QQ 接口** | QFun Plugin API（进程内直接调用） | OneBot v11 协议（HTTP + WebSocket） |

> 两版共享相同的指令集、数据格式、权限模型和多配置架构。**数据文件可互换。**
>
> 📖 详细对比见 [版本详细对比](doc/comparison.md)

## 功能特性

- **多配置架构** — 每个配置独立管理通知群、执行群、权限、记录、黑名单
- **命令可配置** — 全局 `command.json` + 各配置覆盖，支持别名、自定义权限
- **处罚操作** — 踢人 / 禁言 / 警告，支持拉黑（`kick f`）
- **三步检查** — 成员在群 → 状态检查 → 执行 → 执行后验证
- **撤销机制** — 撤销禁言自动解禁，撤销踢黑自动移出黑名单
- **记录查询** — 汇总统计 + 图片表格详情（彩色状态标注）
- **黑名单** — 配置黑名单成员入群自动踢出
- **权限分级** — 多级（0/≥1/-1），各命令可通过 `command.json` `min_level` 控制

## 指令一览

| 指令 | 默认权限 | 格式 | 说明 |
| --- | --- | --- | --- |
| `/help` | -1 | `[唤醒词]help [命令]` | 按配置分组显示可用指令 |
| `/p` | 1 | `[唤醒词]p [配置] <QQ用户> <方式> [内容] <原因>` | 处罚成员 |
| `/rp` | 1 | `[唤醒词]rp [配置] <记录ID> [撤销原因]` | 撤销处罚 |
| `/h` | 1 | `[唤醒词]h [配置] [QQ用户] [-i]` | 查询记录 |
| `/a` | 0 | `[唤醒词]a [配置] <QQ用户> [等级]` | 权限管理（仅超管） |
| `/config` | 0 | `[唤醒词]config <子命令>` | 配置管理（仅超管） |

各版详细用法见对应 README。

## 多配置架构

```text
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

## 快速选择

### 选 QFun 版，如果你…

- QQ 运行在 **Android 手机**上，已安装 QFun 插件框架
- 需要零依赖、放入即用的单文件部署
- 偏好直接在手机上管理群

→ [QFun 版快速开始](QFun/README.md#快速开始)

### 选 OneBot11 版，如果你…

- 有 **Linux / Windows 服务器**，想 24 小时运行
- 使用 **NapCat / LLOneBot / Lagrange / OpenShamrock** 等 OneBot 实现
- 需要模块化代码，便于扩展和二次开发

→ [OneBot11 版快速开始](OneBot11/README.md#快速开始)

## 项目结构

```text
HollowGroupManager/
├── QFun/                    # QFun 插件版（Java/BeanShell）
├── OneBot11/                # OneBot v11 版（Python）
├── doc/                     # 项目文档
│   ├── comparison.md        # 两版详细对比
│   └── development/          # 开发文档（含 QFun/OneBot11 子目录）
└── .github/workflows/       # CI 发布流程
```

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [QFun/README.md](QFun/README.md) | QFun 版安装、配置、使用 |
| [OneBot11/README.md](OneBot11/README.md) | OneBot11 版安装、配置、使用 |
| [doc/comparison.md](doc/comparison.md) | 两版架构、接口、部署详细对比 |
| [doc/development/](doc/development/) | 开发指南、架构设计、添加功能（含 QFun/OneBot11 子目录） |

## 许可证

本项目采用 **GNU Affero General Public License v3.0 (AGPLv3)** 开源许可证。详见 [LICENSE](LICENSE) 文件。

Copyright (C) 2026 Hollow-YK
