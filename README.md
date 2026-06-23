# HollowGroupManager

多群联动管理 Bot — 支持将多个 QQ 群组成管理组，实现跨群同步处罚、记录共享与黑名单联动。

## QFun 版 vs OneBot11 版

本项目提供**两套独立实现**，功能等价，适配不同运行环境：

| 维度 | [QFun 版](QFun/) | [OneBot11 版](OneBot11/) |
| --- | --- | --- |
| **运行平台** | Android（QFun 插件） | 任意平台（Linux / Windows / macOS） |
| **语言** | Java / BeanShell | Python 3.10+ |
| **QQ 接口** | QFun Plugin API（进程内直接调用） | OneBot v11 协议（HTTP + WebSocket） |

> 两版共享相同的指令集、数据格式、权限模型和管理组架构。**数据文件可互换。**
>
> 📖 详细对比见 [版本详细对比](doc/comparison.md)

## 功能特性

- **多群联动** — 一个管理群 + 多个执行群，组内处罚自动同步
- **处罚操作** — 踢人 / 禁言 / 警告，支持拉黑（`kick f`）
- **三步检查** — 成员在群 → 状态检查 → 执行 → 执行后验证
- **撤销机制** — 撤销禁言自动解禁，撤销踢黑自动移出黑名单
- **记录查询** — 汇总统计 + 图片表格详情（彩色状态标注）
- **黑名单** — 组黑名单成员入群自动踢出
- **权限分级** — 超级管理员 / 管理员 / 普通成员三级

## 指令一览

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `/help [命令]` | 0 / 1 | 帮助概览或命令详情 |
| `/p <目标> <方式> [内容] <原因>` | 0 / 1 | 处罚成员（kick / mute / warning） |
| `/rp <记录ID> [撤销原因]` | 0 / 1 | 撤销处罚 |
| `/h [目标] [-i]` | 0 / 1 | 查询记录 |
| `/a <目标> [1/-1]` | 0 | 权限管理（仅超管） |
| `/group <子命令>` | 0 | 管理组配置（仅超管） |

各版详细用法见对应 README。

## 管理组架构

```text
管理群（adminGroup）
  └── 执行群A ── 同步执行处罚
  └── 执行群B ── 同步执行处罚
  └── 执行群C ── 同步执行处罚
```

- 在**管理群**中发起的处罚自动同步到所有**执行群**
- 成员不在某执行群时静默跳过，不视为失败
- 黑名单跨所有执行群共享

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
├── QFun/                    # QFun 插件版
├── OneBot11/                # OneBot v11 版
├── doc/                     # 项目文档
│   ├── comparison.md        # 两版详细对比
│   └── development.md       # 开发文档
└── .github/workflows/       # CI 发布流程
```

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [QFun/README.md](QFun/README.md) | QFun 版安装、配置、使用 |
| [OneBot11/README.md](OneBot11/README.md) | OneBot11 版安装、配置、使用 |
| [doc/comparison.md](doc/comparison.md) | 两版架构、接口、部署详细对比 |
| [doc/development.md](doc/development.md) | 开发指南、架构设计、添加功能 |
| [QFun/AGENTS.md](QFun/AGENTS.md) | QFun 版专属开发提示（BeanShell 注意事项等） |

## 许可证

本项目采用 **GNU Affero General Public License v3.0 (AGPLv3)** 开源许可证。详见 [LICENSE](LICENSE) 文件。

Copyright (C) 2026 Hollow-YK
