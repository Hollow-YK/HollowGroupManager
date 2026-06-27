# OneBot11 功能开发

本文档覆盖功能模块的开发模式：模块结构、指令/事件注册、command.json 配置、help 集成和图片渲染。

## 功能模块模式

每个功能模块是一个类，接收 `CommandDispatcher` 引用，通过它调用 Bot 能力和访问框架服务：

```python
class XxxModule:
    """功能描述"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        """指令处理入口。返回 str=发送文本，None=不响应，""=已自行处理。"""
        ...
```

处理器参数说明：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `level` | `int` | 发送者权限等级（0=超管，-1=路人，≥1=管理员） |
| `sender_id` | `str` | 发送者 QQ 号 |
| `group_id` | `str` | 群号 |
| `parts` | `list[str]` | 分割后的消息（`parts[0]` 为命令名） |
| `at_list` | `list[str]` | @的 QQ 号列表 |
| `sender_card` | `str` | 发送者群名片（card 优先，fallback nickname） |

## 注册指令

在 `main.py` 中实例化模块并注册：

```python
# 普通命令 — 仅在群关联的配置中检查权限
dispatcher.register_command("punish_do", PunishModule(dispatcher).handle)

# 全局命令 — 对所有配置检查权限（help、config 用）
dispatcher.register_command("help", HelpModule(dispatcher).handle, global_check=True)
```

`register_command` 参数：

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `internal` | `str` | 内部命令名（`"help"`, `"punish_do"` 等），与 command.json 中的 key 对应 |
| `handler` | `CmdHandler` | 异步处理函数 |
| `global_check` | `bool` | `True`=对所有配置检查权限（不限于当前群的配置） |

## 注册事件监听

```python
# 注册事件监听器
dispatcher.register_event("notice.group_increase", PunishModule(dispatcher).on_member_join)
```

事件监听器签名：
```python
async def on_xxx(self, event: dict) -> None:
    """处理事件，无返回值"""
```

支持的事件类型：
- `notice.group_increase` — 群成员增加
- `notice.group_decrease` — 群成员减少
- `request.group_add` — 入群请求
- `message.group` — 群消息
- 其它 OneBot v11 事件类型可扩展

## 添加新指令 — 完整步骤

以添加 `/ban` 指令为例：

### 步骤 1：创建功能模块

在 `features/` 下创建新文件（如 `features/basic/ban.py`）：

```python
""" /ban 指令 — 批量禁言 """
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher


class BanModule:
    """批量禁言指令"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        # parts = ["ban", "1h", "@user1", "@user2"]
        # 业务逻辑...
        return "禁言完成"
```

### 步骤 2：在 main.py 中注册

```python
from features.basic.ban import BanModule

dispatcher.register_command("ban", BanModule(dispatcher).handle)
```

### 步骤 3：在 command.json 添加默认配置

在 `CommandConfig.defaults()`（`core/models.py`）中添加：

```python
"ban": CommandItem(enabled=True, names=["ban"], min_level=1),
```

### 步骤 4：在 help 模块添加帮助条目

在 `features/basic/help.py` 的 `HelpModule` 中添加四个字典条目：

```python
_CMD_DESC = {
    ...
    "ban": "批量禁言",
}

_CMD_FORMAT = {
    ...
    "ban": "{w}{cmd} <时长> <@用户...>",
}

_CMD_EXAMPLES = {
    ...
    "ban": ["{w}{cmd} 1h @用户1 @用户2"],
}

_CMD_DETAIL = {
    ...
    "ban": ["> {w}{cmd} <时长> <@用户...>",
            "- <时长>  纯数字=天  组合 1d2h30m",
            "~ {w}{cmd} 1h @用户1 @用户2"],
}
```

### 步骤 5：在 `ORDER` 列表中添加

在 `HelpModule._build_overview_lines()` 中的 `ORDER` 列表末尾添加 `"ban"`，确保在概览中显示。

## command.json 命令配置

### 配置结构

```json
{
  "commands": {
    "内部命令名": {
      "enabled": true,
      "names": ["外部名", "别名...",
      "min_level": 1,
      "sub": {
        "子命令名": {
          "enabled": true,
          "min_level": null
        }
      }
    }
  }
}
```

### 继承与覆盖

```
全局 data/command.json          ← 默认值，所有配置共享
    ↓ (未覆盖时继承)
配置 data/<配置名>/command.json  ← 可覆盖特定命令
    ↓ (未设置字段时继承上级)
子命令                           ← min_level 为 null 时继承父命令
```

### 权限检查逻辑

```
min_level = null → 继承上级
min_level = -1  → 所有人可用
min_level = 0   → 仅超管
min_level = ≥1  → 超管 + 等级 ≤ min_level 的管理员
```

## 图片渲染集成

`features/render.py` 使用 Pillow 渲染帮助图片和处罚记录表格。功能模块可通过 dispatcher 使用：

```python
# 渲染 PNG
png = self.d._render_png(lambda: render_help(title, subtitle, lines))
if png:
    await self.d.send_image(int(group_id), png)
    return ""  # 已自行发送图片，不需要文本回退
# 图片渲染失败 → 回退到纯文本
return self._fallback_text(...)
```

渲染控制：
- `config.json` 中 `render.enabled: false` 可全局关闭图片渲染
- `_render_png` 在 Pillow 未安装或渲染异常时自动返回 `None`
- 功能模块应始终提供纯文本回退逻辑

## 模块间的数据共享

功能模块通过 `dispatcher` 访问共享数据：

```python
# 读取各配置数据
self.d.configs          # dict[str, ConfigState]
self.d.global_commands  # CommandConfig
self.d.super_admins     # set[str]
self.d.wake_words       # list[str]

# 调用框架服务
self.d._find_configs(group_id)        # 查找群的配置
self.d._level(qq)                      # 计算权限
self.d._resolved_commands(cfg)         # 获取完整命令配置
self.d._add_record(...)               # 创建处罚记录
self.d._blacklist_add(...)             # 加入黑名单
```
