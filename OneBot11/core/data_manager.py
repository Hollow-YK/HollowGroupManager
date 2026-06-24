"""
数据持久化 — JSON 文件读写，.tmp 原子写入，.bak 备份恢复。
序列化/反序列化委托给 pydantic。

多配置架构：每个配置一个子目录，包含独立的 5 个 JSON 文件。
"""
import json
import logging
import shutil
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter

from .models import ConfigInfo, CommandConfig, PunishRecord, BlacklistItem

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("Hollow.Data")


class DataManager:
    """JSON 文件持久化管理 — 多配置架构"""

    def __init__(self, data_dir: str):
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    # ==================== 底层文件读写 ====================

    @staticmethod
    def _read_file(path: Path) -> list | dict | None:
        """读 JSON 文件，解析失败返回 None"""
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8").strip()
            return json.loads(text) if text else None
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _write_file(path: Path, data: list | dict):
        """.tmp 原子写入"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            if path.exists():
                path.unlink()
            tmp.rename(path)
        except OSError:
            if tmp.exists():
                tmp.unlink()
            raise

    # ---- 兼容旧接口（委托给 _read_file / _write_file） ----

    def _read_json(self, filename: str) -> list | dict | None:
        return self._read_file(self._dir / filename)

    def _write_json(self, filename: str, data: list | dict):
        self._write_file(self._dir / filename, data)

    def _path(self, filename: str) -> Path:
        return self._dir / filename

    # ==================== 模型序列化（基于路径） ====================

    @staticmethod
    def _load_models_file(path: Path, ta: TypeAdapter) -> list:
        """加载 JSON 数组 → pydantic 模型列表，失败时尝试 .tmp 恢复"""
        data = DataManager._read_file(path)
        if isinstance(data, list):
            try:
                return ta.validate_python(data)
            except Exception:
                logger.warning(f"{path.name} 解析失败，尝试 .tmp 恢复")
        return DataManager._recover_models_file(path, ta)

    @staticmethod
    def _recover_models_file(path: Path, ta: TypeAdapter) -> list:
        tmp = path.with_suffix(path.suffix + ".tmp")
        if not tmp.exists():
            return []
        try:
            data = json.loads(tmp.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            result = ta.validate_python(data)
            if path.exists():
                path.unlink()
            tmp.rename(path)
            logger.info(f"从 .tmp 恢复 {path.name} 成功 ({len(result)} 条)")
            return result
        except Exception:
            return []

    @staticmethod
    def _save_models_file(path: Path, models: list):
        """pydantic 模型列表 → JSON 文件"""
        DataManager._write_file(path,
            [m.model_dump(mode="json", by_alias=True, exclude_unset=True) for m in models])

    @staticmethod
    def _save_dict_file(path: Path, data: dict):
        DataManager._write_file(path, data)

    # ==================== 配置目录管理 ====================

    def list_configs(self) -> list[str]:
        """扫描 data/ 下所有配置子目录（含有 groups.json 的）"""
        names = sorted(
            d.name for d in self._dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
            and (d / "groups.json").exists()
        )
        return names

    def _config_dir(self, name: str) -> Path:
        """获取配置子目录路径，自动创建"""
        p = self._dir / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def remove_config(self, name: str):
        """删除配置目录及所有文件"""
        p = self._dir / name
        if p.exists() and p.is_dir():
            shutil.rmtree(p)
            logger.info(f"已删除配置目录: {name}")

    def rename_config(self, old_name: str, new_name: str):
        """重命名配置目录"""
        old = self._dir / old_name
        new = self._dir / new_name
        if old.exists() and old.is_dir():
            old.rename(new)
            logger.info(f"配置重命名: {old_name} → {new_name}")

    # ==================== 单配置的 groups.json ====================

    def load_config_info(self, name: str) -> ConfigInfo:
        """加载配置的群组信息"""
        p = self._config_dir(name) / "groups.json"
        data = self._read_file(p)
        if isinstance(data, dict):
            try:
                return ConfigInfo.model_validate(data)
            except Exception:
                logger.warning(f"[{name}] groups.json 解析失败")
        return ConfigInfo()

    def save_config_info(self, name: str, info: ConfigInfo):
        """保存配置的群组信息"""
        p = self._config_dir(name) / "groups.json"
        self._write_file(p, info.model_dump(mode="json", by_alias=True))

    # ==================== 单配置的 records.json ====================

    _records_ta = TypeAdapter(list[PunishRecord])

    def load_config_records(self, name: str) -> list[PunishRecord]:
        p = self._config_dir(name) / "records.json"
        return self._load_models_file(p, self._records_ta)

    def save_config_records(self, name: str, records: list[PunishRecord]):
        p = self._config_dir(name) / "records.json"
        self._save_models_file(p, records)

    # ==================== 单配置的 permissions.json ====================

    def load_config_permissions(self, name: str) -> dict[str, int]:
        p = self._config_dir(name) / "permissions.json"
        data = self._read_file(p)
        result: dict[str, int] = {}
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    level = int(v)
                    if level >= 1 or level == -1:
                        result[str(k)] = level
                except (ValueError, TypeError):
                    pass
        return result

    def save_config_permissions(self, name: str, permissions: dict[str, int]):
        p = self._config_dir(name) / "permissions.json"
        self._save_dict_file(p, {str(k): int(v) for k, v in permissions.items()})

    # ==================== 单配置的 blacklist.json ====================

    _blacklist_ta = TypeAdapter(list[BlacklistItem])

    def load_config_blacklist(self, name: str) -> list[BlacklistItem]:
        p = self._config_dir(name) / "blacklist.json"
        return self._load_models_file(p, self._blacklist_ta)

    def save_config_blacklist(self, name: str, blacklist: list[BlacklistItem]):
        p = self._config_dir(name) / "blacklist.json"
        self._save_models_file(p, blacklist)

    # ==================== 全局 command.json（data/command.json） ====================

    def load_global_commands(self) -> CommandConfig:
        """加载全局命令配置"""
        p = self._dir / "command.json"
        data = self._read_file(p)
        if isinstance(data, dict):
            try:
                return CommandConfig.model_validate(data)
            except Exception:
                logger.warning("全局 command.json 解析失败")
        return CommandConfig.defaults()

    def save_global_commands(self, commands: CommandConfig):
        """保存全局命令配置"""
        p = self._dir / "command.json"
        self._write_file(p, commands.model_dump(mode="json", by_alias=True))

    # ==================== 单配置的 command.json（合并全局） ====================

    def load_config_commands(self, name: str) -> CommandConfig:
        """加载各配置自己的命令配置（仅包含显式设置的项，无则返回空）"""
        p = self._config_dir(name) / "command.json"
        data = self._read_file(p)
        if isinstance(data, dict):
            try:
                return CommandConfig.model_validate(data)
            except Exception:
                logger.warning(f"[{name}] command.json 解析失败")
        return CommandConfig(commands={})

    def save_config_commands(self, name: str, commands: CommandConfig):
        """保存各配置的命令配置（仅保存与全局不同的项）"""
        # 直接全量保存，简洁可靠
        p = self._config_dir(name) / "command.json"
        self._write_file(p, commands.model_dump(mode="json", by_alias=True))

    # ==================== 批量保存 ====================

    def save_config(self, name: str, state: "ConfigState"):
        """保存一个配置的全部 5 个文件"""
        self.save_config_info(name, state.info)
        self.save_config_commands(name, state.commands)
        self.save_config_records(name, state.records)
        self.save_config_permissions(name, state.permissions)
        self.save_config_blacklist(name, state.blacklist)

    # ==================== 启动校验 ====================

    def check_all(self):
        """确保全局 command.json 和至少一个配置存在"""
        # 全局 command.json
        if not (self._dir / "command.json").exists():
            self.save_global_commands(CommandConfig.defaults())
            logger.info("已创建全局 command.json")

        # 默认配置
        configs = self.list_configs()
        if not configs:
            self.save_config_info("default", ConfigInfo())
            self.save_config_commands("default", CommandConfig(commands={}))
            logger.info("已创建默认配置 'default'")
