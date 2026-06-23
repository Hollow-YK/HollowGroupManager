"""
数据模型 — pydantic BaseModel，自动序列化/校验，snake_case ↔ camelCase
"""
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _to_camel(name: str) -> str:
    """snake_case → camelCase"""
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class ManagementGroup(BaseModel):
    """管理组"""
    name: str = ""
    admin_group: str = Field(default="", alias="adminGroup")
    execution_groups: set[str] = Field(default_factory=set, alias="executionGroups")

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


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


# 权限直接用 dict[str, int]，不需要 pydantic 模型
