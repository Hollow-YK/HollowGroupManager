# 多群联动管理Bot — QFun 版

基于 [QFun](https://github.com/YuShengXiang1/QFun-Plugin) 框架的 QQ 群违规管理插件。支持将多个 QQ 群组成管理组，实现跨群同步处罚、记录共享与黑名单联动。

> 本项目另提供 [OneBot11 版](../OneBot11/README.md)，基于 OneBot v11 协议，纯 Python 实现，可在服务器上运行。两版功能等价、数据格式兼容。
>
> 📖 [详细对比](../doc/comparison.md) · [开发文档](../doc/development/QFun/) · [项目总览](../README.md)

## 快速开始

### 1. 安装

从 [Releases](https://github.com/Hollow-YK/HollowGroupManager/releases) 下载 `HollowGroupManager_QFun-x.x.x.zip`，解压到 QFun 插件目录：

```text
/storage/emulated/0/Android/data/com.tencent.mobileqq/QFun/<QQ号>/plugin/
```

### 2. 配置

编辑 `多群管理Bot/config.properties`：

```properties
wakeWords=/,!,。
superAdmins=你的QQ号,另一个超级管理员QQ
dataDir=data
```

| 字段 | 说明 |
| --- | --- |
| `wakeWords` | 唤醒前缀，逗号分隔（如 `/,!,。`） |
| `superAdmins` | 超级管理员 QQ，逗号分隔（必须配置） |
| `dataDir` | 数据目录名，相对路径 |

### 3. 使用

在 QFun 中加载插件，然后在目标群发送指令：

```text
/config new 配置名称         → 创建配置
/config 配置名称 set         → 在其他群加入为执行群
/help                       → 查看所有指令
```

## 指令参考

> `[唤醒词]` 为 `config.properties` 中配置的唤醒前缀（默认 `/`、`!`、`。`）。`QQ用户` 支持 @某人 或 QQ 号。命令名可通过 `command.json` 自定义（如 `/p` 别名 `/punish`）。

| 指令 | 默认权限 | 格式 | 说明 |
| --- | --- | --- | --- |
| `/help` | -1 | `[唤醒词]help [命令]` | 按配置分组显示可用指令 |
| `/p` | 1 | `[唤醒词]p [配置] <QQ用户> <方式> [内容] <原因>` | 处罚：`kick [f]` / `mute 时长` / `warn` |
| `/h` | 1 | `[唤醒词]h [配置] [QQ用户] [-i]` | 查询：无参=表格 / 有参=汇总 / `-i`=详情 |
| `/rp` | 1 | `[唤醒词]rp [配置] <记录ID> [撤销原因]` | 撤销处罚（多配置群必填配置名） |
| `/a` | 0 | `[唤醒词]a [配置] <QQ用户> [等级]` | 设权限等级（-1=普通，≥1 数字越大越低） |
| `/config` | 0 | `[唤醒词]config <子命令>` | 配置管理：new / rename / notify / set / remove / group |

禁言时长：纯数字=天，支持 `1d2h30m`、`3h`、`30m` 等组合格式。各命令的启用、名称、权限要求可在 `data/command.json`（全局）和各配置的 `command.json` 中自定义。

### 处罚示例

```text
/p @某人 mute 1d2h 广告刷屏     → 禁言 1 天 2 小时
/p 123456 kick f 严重违规        → 踢出并加入黑名单
/p @某人 warn 注意言辞           → 警告
/p 反馈组 @某人 mute 1d 测试     → 在指定配置中执行
```

## 权限等级

| 等级 | 角色 | 配置方式 | 权限 |
| --- | --- | --- | --- |
| 0 | 超级管理员 | `config.properties` → `superAdmins` | 全部指令 |
| ≥1 | 管理员 | `/a` 指令设置 | 数字越小权限越高（受 `command.json` 中 `min_level` 限制） |
| -1 | 普通成员 | 默认 | 仅 `min_level: -1` 的命令 |

## 文件结构

```text
多群管理Bot/
├── main.java           # 主脚本（单文件）
├── config.properties   # 唤醒词、超管等配置
├── info.prop           # 插件元信息
├── desc.txt            # 插件描述
├── README.md           # 本文档
├── AGENTS.md           # 开发者文档（BeanShell 注意事项等）
├── history.txt         # 版本历史
├── LICENSE             # AGPLv3
└── data/               # 运行时数据（自动生成）
    ├── command.json    # 全局命令配置（默认值）
    └── <配置名>/        # 各配置独立目录
        ├── groups.json         # 通知群 + 执行群
        ├── command.json        # 命令覆盖（可选）
        ├── permissions.json    # 权限映射
        └── punish/             # 处罚子系统
            ├── records.json    # 处罚记录
            └── blacklist.json  # 黑名单
```

## 配置系统

### 全局命令配置 (`data/command.json`)

自动生成，定义所有命令的默认行为。各配置目录下的 `command.json` 可覆盖特定命令（未覆盖项自动继承全局）。

### 多配置架构

每个配置独立管理：通知群、执行群、权限、处罚记录、黑名单。一个群可属于多个配置。`/help` 按配置分组显示可用指令。

## 数据兼容

采用 `.tmp` 原子写入防止数据损坏，加载失败时自动尝试 `.tmp` 恢复。

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | QFun 专属开发提示（BeanShell 类型陷阱、线程安全等） |
| [doc/comparison.md](../doc/comparison.md) | QFun vs OneBot11 详细对比 |
| [doc/development/QFun/](../doc/development/QFun/) | 开发指南（添加指令、数据持久化等） |
| [根目录 README](../README.md) | 项目总览 |

## 许可证

GNU Affero General Public License v3.0 — 详见 [LICENSE](LICENSE)。
