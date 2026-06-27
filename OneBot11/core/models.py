"""
数据模型 — pydantic BaseModel，自动序列化/校验，snake_case ↔ camelCase
"""
from dataclasses import dataclass, field
from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field, model_validator


def _to_camel(name: str) -> str:
    """snake_case → camelCase"""
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class ConfigInfo(BaseModel):
    """单个配置的群组信息"""
    notify_group: Optional[str] = Field(default=None, alias="notifyGroup")
    execution_groups: set[str] = Field(default_factory=set, alias="executionGroups")

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


class CommandItem(BaseModel):
    """单条命令配置。sub 为子命令字典，支持递归。"""
    enabled: bool = True
    names: List[str] = Field(default_factory=list)  # 命令名列表，如 ["p", "punish"]
    min_level: Optional[int] = None  # None=继承上级，-1=所有人，0=超管，≥1 越小越高
    sub: Optional[Dict[str, "CommandItem"]] = None

    model_config = {"populate_by_name": True}


class CommandConfig(BaseModel):
    """命令配置集合，key 为内部命令名"""
    commands: Dict[str, CommandItem] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    @classmethod
    def defaults(cls) -> "CommandConfig":
        return cls(commands={
            "help":           CommandItem(enabled=True, names=["help"], min_level=-1),
            "config":         CommandItem(enabled=True, names=["config"], min_level=0, sub={
                "new":    CommandItem(enabled=True),
                "rename": CommandItem(enabled=True),
                "notify": CommandItem(enabled=True),
                "set":    CommandItem(enabled=True),
                "remove": CommandItem(enabled=True),
                "group":  CommandItem(enabled=True),
                "list":   CommandItem(enabled=True),
            }),
            "admin":          CommandItem(enabled=True, names=["admin", "a"], min_level=0),
            "punish_do":      CommandItem(enabled=True, names=["punish", "p"], min_level=1),
            "punish_revoke":  CommandItem(enabled=True, names=["revokepunish", "rp"], min_level=1),
            "punish_history": CommandItem(enabled=True, names=["history", "h"], min_level=1),
            "approval":       CommandItem(enabled=True, names=["approval", "ap"], min_level=1, sub={
                "on":       CommandItem(enabled=True),
                "off":      CommandItem(enabled=True),
                "status":   CommandItem(enabled=True, min_level=-1),
                "regex":    CommandItem(enabled=True),
                "reject":   CommandItem(enabled=True),
                "mismatch": CommandItem(enabled=True),
                "welcome":  CommandItem(enabled=True),
            }),
            "verify":         CommandItem(enabled=True, names=["verify", "v"], min_level=1, sub={
                "on":       CommandItem(enabled=True),
                "off":      CommandItem(enabled=True),
                "status":   CommandItem(enabled=True),
                "welcome":  CommandItem(enabled=True),
                "maxerr":   CommandItem(enabled=True),
                "retry":    CommandItem(enabled=True),
                "timeout":    CommandItem(enabled=True),
                "bottimeout": CommandItem(enabled=True),
                "block":    CommandItem(enabled=True, sub={
                    "add":    CommandItem(enabled=True),
                    "remove": CommandItem(enabled=True),
                    "list":   CommandItem(enabled=True),
                    "move":   CommandItem(enabled=True),
                    "edit":   CommandItem(enabled=True),
                }),
                "question": CommandItem(enabled=True, sub={
                    "add":    CommandItem(enabled=True),
                    "remove": CommandItem(enabled=True),
                    "list":   CommandItem(enabled=True),
                    "edit":   CommandItem(enabled=True),
                }),
            }),
        })


@dataclass
class ConfigState:
    """单个配置的运行时完整状态"""
    name: str
    info: ConfigInfo = field(default_factory=ConfigInfo)
    commands: CommandConfig = field(default_factory=lambda: CommandConfig(commands={}))
    records: List["PunishRecord"] = field(default_factory=list)
    records_by_id: Dict[int, "PunishRecord"] = field(default_factory=dict)
    permissions: Dict[str, int] = field(default_factory=dict)
    blacklist: List["BlacklistItem"] = field(default_factory=list)
    next_rid: int = 1


class PunishRecord(BaseModel):
    """处罚记录"""
    id: int = 0
    sender: int = 0
    time: int = 0
    from_group: str = Field(default="", alias="fromGroup")
    target: int = 0
    method: str = ""          # kick / mute / warn
    content: str = ""         # f / 时长 / 空
    reason: str = ""
    status: str = ""          # 不合规 / 已执行 / 执行失败 / 部分失败 / 已撤销
    fail_detail: str = Field(default="", alias="failDetail")
    revoke_time: int = Field(default=0, alias="revokeTime")
    revoke_reason: str = Field(default="", alias="revokeReason")

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}

    @model_validator(mode="before")
    @classmethod
    def _coerce_ints(cls, data: Any) -> Any:
        """兼容 Java 版可能出现的字符串数字"""
        if isinstance(data, dict):
            for field_name in ("id", "sender", "time", "target", "revokeTime"):
                if field_name in data:
                    try:
                        data[field_name] = int(data[field_name])
                    except (TypeError, ValueError):
                        pass
        return data

    def describe(self) -> str:
        c = self.content or ""
        if self.method == "kick":
            return "kick" + (" f" if c == "f" else "")
        if self.method == "mute":
            return f"mute {c}"
        if self.method == "warn":
            return "warn"
        return self.method or ""


class BlacklistItem(BaseModel):
    """黑名单条目"""
    qq: int = 0
    reason: str = ""
    add_time: int = Field(default=0, alias="addTime")
    group_name: str = Field(default="", alias="groupName")

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}

    @model_validator(mode="before")
    @classmethod
    def _coerce_ints(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field_name in ("qq", "addTime"):
                if field_name in data:
                    try:
                        data[field_name] = int(data[field_name])
                    except (TypeError, ValueError):
                        pass
        return data


# 递归类型支持
CommandItem.model_rebuild()


# 权限直接用 dict[str, int]，不需要 pydantic 模型
