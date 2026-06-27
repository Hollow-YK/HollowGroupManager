# OneBot11 数据开发

本文档覆盖数据层的开发：Pydantic 数据模型、DataManager 持久化、配置文件管理和扩展方法。

## Pydantic 数据模型（core/models.py）

### 模型总览

| 模型 | 类型 | 用途 |
| --- | --- | --- |
| `ConfigInfo` | `BaseModel` | 单个配置的群组信息（通知群 + 执行群） |
| `CommandItem` | `BaseModel` | 单条命令配置（启用/名称/权限/子命令） |
| `CommandConfig` | `BaseModel` | 命令配置集合 |
| `ConfigState` | `dataclass` | 单个配置的运行时完整状态 |
| `PunishRecord` | `BaseModel` | 处罚记录 |
| `BlacklistItem` | `BaseModel` | 黑名单条目 |

### ConfigInfo — 群组信息

```python
class ConfigInfo(BaseModel):
    notify_group: Optional[str] = Field(default=None, alias="notifyGroup")
    execution_groups: set[str] = Field(default_factory=set, alias="executionGroups")

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}
```

`alias_generator` 自动将 snake_case 字段名映射到 camelCase JSON key（如 `execution_groups` ↔ `executionGroups`）。`populate_by_name=True` 允许两种格式均可反序列化。

### CommandItem / CommandConfig — 命令配置

```python
class CommandItem(BaseModel):
    enabled: bool = True
    names: List[str] = Field(default_factory=list)
    min_level: Optional[int] = None    # None=继承上级
    sub: Optional[Dict[str, "CommandItem"]] = None

class CommandConfig(BaseModel):
    commands: Dict[str, CommandItem] = Field(default_factory=dict)

    @classmethod
    def defaults(cls) -> "CommandConfig":
        """所有命令的默认配置"""
        return cls(commands={...})
```

关键约定：
- `min_level: None` — 未设置，继承上级或全局
- `min_level: -1` — 所有人可用
- `min_level: 0` — 仅超管
- `min_level: ≥1` — 超管 + 对应等级管理员
- `sub` — 递归子命令结构，支持 `/config new` 等

### PunishRecord — 处罚记录

```python
class PunishRecord(BaseModel):
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
    revokepunish_time: int = Field(default=0, alias="revokepunishTime")
    revokepunish_reason: str = Field(default="", alias="revokepunishReason")

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}

    @model_validator(mode="before")
    @classmethod
    def _coerce_ints(cls, data: Any) -> Any:
        """兼容 Java 版可能出现的字符串数字"""
        if isinstance(data, dict):
            for field_name in ("id", "sender", "time", "target", "revokepunishTime"):
                if field_name in data:
                    try:
                        data[field_name] = int(data[field_name])
                    except (TypeError, ValueError):
                        pass
        return data
```

`@model_validator(mode="before")` 在 Pydantic 校验前执行，将 Java 版可能产生的字符串数字转为 int，确保两版数据兼容。

### ConfigState — 运行时状态

```python
@dataclass
class ConfigState:
    """单个配置的运行时完整状态"""
    name: str
    info: ConfigInfo
    commands: CommandConfig
    records: List[PunishRecord]
    records_by_id: Dict[int, PunishRecord]    # ID → 记录索引
    permissions: Dict[str, int]                # QQ → 权限等级
    blacklist: List[BlacklistItem]
    next_rid: int = 1                          # 下一条记录 ID
```

注意：`ConfigState` 是 `@dataclass` 而非 `BaseModel`——它是运行时对象，不直接序列化。

## DataManager 持久化（core/data_manager.py）

### 多配置目录结构

```
data/
├── command.json              # 全局命令配置
├── <配置名>/                  # 各配置独立目录
│   ├── groups.json           # ConfigInfo
│   ├── command.json          # 配置级命令覆盖（可选）
│   ├── permissions.json      # {QQ号: 权限等级}
│   ├── verify_config.json    # 进群验证方案（v1.0.6）
│   ├── approval_config.json  # 加群审批方案（v1.0.6）
│   ├── verify_groups.json    # 群验证开关（v1.0.6）
│   └── punish/
│       ├── records.json      # [PunishRecord]
│       └── blacklist.json    # [BlacklistItem]
```

### 原子写入

所有写入操作使用 `.tmp` 原子写入：

```python
@staticmethod
def _write_file(path: Path, data: list | dict):
    """.tmp 原子写入 — 先写临时文件，再原子重命名"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    if path.exists():
        path.unlink()
    tmp.rename(path)  # 原子操作
```

### 安全加载 + .tmp 恢复

```python
@staticmethod
def _load_models_file(path: Path, ta: TypeAdapter) -> list:
    """加载 JSON → pydantic 列表，失败时自动尝试 .tmp 恢复"""
    data = DataManager._read_file(path)
    if isinstance(data, list):
        try:
            return ta.validate_python(data)
        except Exception:
            logger.warning(f"{path.name} 解析失败，尝试 .tmp 恢复")
    return DataManager._recover_models_file(path, ta)

@staticmethod
def _recover_models_file(path: Path, ta: TypeAdapter) -> list:
    """从 .tmp 恢复数据，恢复成功后将 .tmp 改名覆盖损坏文件"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    if not tmp.exists():
        return []
    ...
```

恢复策略：
1. 主文件解析失败 → 检查 `.tmp` 是否存在
2. `.tmp` 存在且可解析 → 恢复数据，用 `.tmp` 覆盖损坏文件
3. 都无法恢复 → 返回空数据

### TypeAdapter 模式

DataManager 使用 Pydantic `TypeAdapter` 进行列表序列化：

```python
_records_ta = TypeAdapter(list[PunishRecord])

def load_config_records(self, name: str) -> list[PunishRecord]:
    p = self._punish_dir(name) / "records.json"
    return self._load_models_file(p, self._records_ta)
```

序列化时使用 `model_dump(mode="json", by_alias=True, exclude_unset=True)`：
- `mode="json"` — JSON 兼容输出
- `by_alias=True` — 使用 camelCase 别名
- `exclude_unset=True` — 排除未设置的默认值字段

### 配置生命周期

```
启动 → check_all()  确保全局 command.json 和默认配置存在
     → load()       加载所有配置子目录数据
     → ... 运行 ...
退出 → save()       遍历 configs，调用 save_config() 全量持久化
```

## 添加新数据持久化 — 完整步骤

以添加 `/welcome` 入群欢迎功能为例：

### 步骤 1：定义数据模型

在 `core/models.py` 中添加：

```python
class WelcomeConfig(BaseModel):
    enabled: bool = False
    message: str = "欢迎 {nickname} 加入本群！"
    target_groups: set[str] = Field(default_factory=set)
```

### 步骤 2：在 ConfigState 添加字段

```python
@dataclass
class ConfigState:
    ...
    welcome: WelcomeConfig = field(default_factory=WelcomeConfig)
```

### 步骤 3：在 DataManager 添加读写方法

```python
def load_config_welcome(self, name: str) -> WelcomeConfig:
    p = self._config_dir(name) / "welcome.json"
    data = self._read_file(p)
    if isinstance(data, dict):
        try:
            return WelcomeConfig.model_validate(data)
        except Exception:
            logger.warning(f"[{name}] welcome.json 解析失败")
    return WelcomeConfig()

def save_config_welcome(self, name: str, welcome: WelcomeConfig):
    p = self._config_dir(name) / "welcome.json"
    self._write_file(p, welcome.model_dump(mode="json", by_alias=True))
```

### 步骤 4：更新 save_config 和 load

在 `DataManager.save_config()` 中添加：
```python
self.save_config_welcome(name, state.welcome)
```

在 `CommandDispatcher.load()` 的配置加载循环中添加：
```python
welcome = self.dm.load_config_welcome(name)
# 存入 ConfigState
```

## config.json 配置管理

### 配置结构

```json
{
  "onebot": {
    "mode": "http_ws",
    "http_url": "http://127.0.0.1:3000",
    "ws_url": "ws://127.0.0.1:3001",
    "ws_reverse_port": 8080,
    "access_token": ""
  },
  "plugin": {
    "wake_words": ["/", "!", "。"],
    "super_admins": ["123456789"],
    "data_dir": "data"
  },
  "render": { "enabled": true },
  "log": {
    "log_to_file": true,
    "log_level": "INFO",
    "log_dir": "logs"
  }
}
```

### 添加新配置项

1. 在 `main.py` 的 `load_config()` 默认值模板中添加字段
2. 在 `main()` 中读取对应的配置段：

```python
cfg = load_config()
new_section = cfg.get("new_section", {})
some_value = new_section.get("some_key", "default_value")
```

3. 将值传递到需要的组件构造函数中
