# 多群联动管理Bot — QFun 版

基于 [QFun](https://github.com/YuShengXiang1/QFun-Plugin) 框架的 QQ 群违规管理插件。支持将多个 QQ 群组成管理组，实现跨群同步处罚、记录共享与黑名单联动。

> 本项目另提供 [OneBot11 版](../OneBot11/README.md)，基于 OneBot v11 协议，纯 Python 实现，可在服务器上运行。两版功能等价、数据格式兼容。
>
> 📖 [详细对比](../doc/comparison.md) · [开发文档](../doc/development.md) · [项目总览](../README.md)

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
/group admin 管理组名称     → 将当前群设为管理群，创建管理组
/group set 管理组名称       → 在其他群加入为执行群
/help                       → 查看所有指令
```

## 指令参考

> `[唤醒词]` 为 `config.properties` 中配置的唤醒前缀（默认 `/`、`!`、`。`）。`QQ用户` 支持 @某人 或 QQ 号。

| 指令 | 权限 | 格式 | 说明 |
| --- | --- | --- | --- |
| `/help` | 0 / 1 | `[唤醒词]help [命令]` | 指令列表或命令详情 |
| `/p` | 0 / 1 | `[唤醒词]p <QQ用户> <方式> [内容] <原因>` | 处罚：`kick [f]` / `mute 时长` / `warning` |
| `/h` | 0 / 1 | `[唤醒词]h [QQ用户] [-i]` | 查询：无参=全部表格 / 有参=汇总 / `-i`=详情表格 |
| `/rp` | 0 / 1 | `[唤醒词]rp <记录ID> [撤销原因]` | 撤销处罚（禁言自动解禁，踢黑移出黑名单） |
| `/a` | 0 | `[唤醒词]a <QQ用户> [1/-1]` | 设管理员（1）或降级（-1）；超管只能在配置文件中设定 |
| `/group` | 0 | `[唤醒词]group <admin\|set\|remove\|info>` | 管理组配置 |

**禁言时长**：纯数字=天，支持 `1d2h30m`、`3h`、`30m` 等组合格式。

**处罚示例**：

```text
/p @某人 mute 1d2h 广告刷屏     → 禁言 1 天 2 小时
/p 123456 kick f 严重违规        → 踢出并加入黑名单
/p @某人 warning 注意言辞        → 警告
```

## 权限等级

| 等级 | 角色 | 配置方式 | 权限 |
| --- | --- | --- | --- |
| 0 | 超级管理员 | `config.properties` → `superAdmins` | 全部指令 |
| 1 | 管理员 | `/a` 指令设置 | 处罚、查询、撤销 |
| -1 | 普通成员 | 默认 | 不响应指令 |

## 文件结构

```text
多群管理Bot/
├── main.java           # 主脚本（单文件，~1900 行）
├── config.properties   # 唤醒词、超管等配置
├── info.prop           # 插件元信息
├── desc.txt            # 插件描述
├── README.md           # 本文档
├── AGENTS.md           # 开发者文档（BeanShell 注意事项等）
├── history.txt         # 版本历史
├── LICENSE             # AGPLv3
└── data/               # 运行时数据（自动生成）
    ├── groups.json
    ├── records.json
    ├── permissions.json
    └── blacklist.json
```

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | QFun 专属开发提示（BeanShell 类型陷阱、线程安全等） |
| [doc/comparison.md](../doc/comparison.md) | QFun vs OneBot11 详细对比 |
| [doc/development.md](../doc/development.md) | 开发指南（添加指令、数据持久化等） |
| [根目录 README](../README.md) | 项目总览 |

## 许可证

GNU Affero General Public License v3.0 — 详见 [LICENSE](LICENSE)。
