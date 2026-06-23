"""
数据持久化 — JSON 文件读写，.tmp 原子写入，.bak 备份恢复。
序列化/反序列化委托给 pydantic。
"""
import json
import logging
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from .models import ManagementGroup, PunishRecord, BlacklistItem

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("Hollow.Data")


class DataManager:
    """JSON 文件持久化管理"""

    def __init__(self, data_dir: str):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, filename: str) -> Path:
        return self._dir / filename

    # ==================== 原子写入 ====================

    def _read_json(self, filename: str) -> list | dict | None:
        """读 JSON，解析失败返回 None"""
        p = self._path(filename)
        if not p.exists():
            return None
        try:
            text = p.read_text(encoding="utf-8").strip()
            return json.loads(text) if text else None
        except (json.JSONDecodeError, OSError):
            return None

    def _write_json(self, filename: str, data: list | dict):
        """.tmp 原子写入"""
        p = self._path(filename)
        tmp = self._path(filename + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            if p.exists():
                p.unlink()
            tmp.rename(p)
        except OSError:
            if tmp.exists():
                tmp.unlink()
            raise

    # ==================== 带恢复的批量加载 ====================

    def _load_models(self, filename: str, ta: TypeAdapter) -> list:
        """加载 JSON 数组 → pydantic 模型列表，失败时尝试 .tmp 恢复"""
        data = self._read_json(filename)
        if isinstance(data, list):
            try:
                return ta.validate_python(data)
            except Exception:
                logger.warning(f"{filename} 解析失败，尝试 .tmp 恢复")
        return self._recover_models(filename, ta)

    def _recover_models(self, filename: str, ta: TypeAdapter) -> list:
        tmp = self._path(filename + ".tmp")
        if not tmp.exists():
            return []
        try:
            data = json.loads(tmp.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            result = ta.validate_python(data)
            p = self._path(filename)
            if p.exists():
                p.unlink()
            tmp.rename(p)
            logger.info(f"从 .tmp 恢复 {filename} 成功 ({len(result)} 条)")
            return result
        except Exception:
            return []

    def _save_models(self, filename: str, models: list):
        """pydantic 模型列表 → JSON 文件"""
        self._write_json(filename,
                         [m.model_dump(mode="json", by_alias=True, exclude_unset=True) for m in models])

    def _save_dict(self, filename: str, data: dict):
        self._write_json(filename, data)

    # ==================== 管理组 ====================

    def load_groups(self) -> dict[str, ManagementGroup]:
        data = self._read_json("groups.json")
        result: dict[str, ManagementGroup] = {}
        if isinstance(data, list):
            try:
                for item in data:
                    g = ManagementGroup.model_validate(item)
                    result[g.name] = g
            except Exception:
                logger.warning("groups.json 解析失败")
        return result

    def save_groups(self, groups: dict[str, ManagementGroup]):
        self._write_json("groups.json",
                         [g.model_dump(mode="json", by_alias=True) for g in groups.values()])

    # ==================== 处罚记录 ====================

    _records_ta = TypeAdapter(list[PunishRecord])

    def load_records(self) -> list[PunishRecord]:
        return self._load_models("records.json", self._records_ta)

    def save_records(self, records: list[PunishRecord]):
        self._save_models("records.json", records)

    # ==================== 权限 ====================

    def load_permissions(self) -> dict[str, int]:
        data = self._read_json("permissions.json")
        result: dict[str, int] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    level = int(v)
                    if level in (1, -1):
                        result[str(k)] = level
                except (ValueError, TypeError):
                    pass
        return result

    def save_permissions(self, permissions: dict[str, int]):
        self._write_json("permissions.json",
                         {str(k): int(v) for k, v in permissions.items()})

    # ==================== 黑名单 ====================

    _blacklist_ta = TypeAdapter(list[BlacklistItem])

    def load_blacklist(self) -> list[BlacklistItem]:
        return self._load_models("blacklist.json", self._blacklist_ta)

    def save_blacklist(self, blacklist: list[BlacklistItem]):
        self._save_models("blacklist.json", blacklist)

    # ==================== 启动校验 ====================

    def check_all(self):
        self._ensure("groups.json", [])
        self._ensure("records.json", [])
        self._ensure("permissions.json", {})
        self._ensure("blacklist.json", [])

    def _ensure(self, filename: str, default):
        p = self._path(filename)
        if p.exists():
            data = self._read_json(filename)
            if data is not None and type(data) == type(default):
                return
            bak = self._path(filename + ".bak")
            if bak.exists():
                bak.unlink()
            p.rename(bak)
            logger.warning(f"{filename} 已损坏，已备份为 .bak 并重建")
        self._write_json(filename, default)
