#!/usr/bin/env python3
"""
旧版数据 → 多配置架构迁移脚本

完全独立，不依赖项目任何模块，可单独复制使用。

用法：
    python migrate.py              # 默认 ../data（相对于脚本位置）
    python migrate.py /path/to/data

流程：
    1. 将旧 data/ 下全部文件打包为 backup/legacy_<时间戳>.zip
    2. 每个 ManagementGroup → 一个独立新配置子目录
    3. 旧文件打包后删除
"""
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path


def read_json(path: Path) -> list | dict | None:
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else None
    except (json.JSONDecodeError, OSError):
        return None


def write_json(path: Path, data: list | dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        if path.exists():
            path.unlink()
        tmp.rename(path)
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise


def migrate(data_dir: str):
    data = Path(data_dir)
    if not data.exists():
        print(f"[跳过] 数据目录不存在: {data}")
        return

    # 检查是否已有配置子目录
    subdirs = [d for d in data.iterdir() if d.is_dir() and not d.name.startswith(".")]
    if subdirs:
        print(f"[跳过] 已有 {len(subdirs)} 个配置子目录，无需迁移")
        return

    # 检查旧数据文件
    groups_file = data / "groups.json"
    if not groups_file.exists():
        print("[跳过] 未发现旧版 groups.json")
        return

    records_file = data / "records.json"
    permissions_file = data / "permissions.json"
    blacklist_file = data / "blacklist.json"

    print("=== 旧版数据迁移 ===")

    # ---- 1. 备份 ----
    backup_dir = data / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = backup_dir / f"legacy_{ts}.zip"

    legacy_files = []
    for fname in ("groups.json", "records.json", "permissions.json", "blacklist.json"):
        fp = data / fname
        if fp.exists():
            legacy_files.append(fp)

    if legacy_files:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for fp in legacy_files:
                zf.write(fp, fp.name)
        print(f"  旧数据已备份: {zip_path}")
        for fp in legacy_files:
            fp.unlink()
            print(f"  已删除: {fp.name}")

    # 从 zip 中读取旧数据
    with zipfile.ZipFile(zip_path, "r") as zf:
        # 读取 groups.json
        groups_data = []
        if "groups.json" in zf.namelist():
            raw = zf.read("groups.json").decode("utf-8")
            groups_data = json.loads(raw)
            if not isinstance(groups_data, list):
                groups_data = []

        # 读取 records.json
        records_data = []
        if "records.json" in zf.namelist():
            raw = zf.read("records.json").decode("utf-8")
            records_data = json.loads(raw)
            if not isinstance(records_data, list):
                records_data = []

        # 读取 permissions.json
        permissions_data = {}
        if "permissions.json" in zf.namelist():
            raw = zf.read("permissions.json").decode("utf-8")
            permissions_data = json.loads(raw)
            if not isinstance(permissions_data, dict):
                permissions_data = {}

        # 读取 blacklist.json
        blacklist_data = []
        if "blacklist.json" in zf.namelist():
            raw = zf.read("blacklist.json").decode("utf-8")
            blacklist_data = json.loads(raw)
            if not isinstance(blacklist_data, list):
                blacklist_data = []

    # ---- 2. 迁移 ----
    if not groups_data:
        # 没有管理组，创建一个默认配置
        config_dir = data / "default"
        punish_dir = config_dir / "punish"
        punish_dir.mkdir(parents=True, exist_ok=True)
        write_json(config_dir / "groups.json",
                   {"notifyGroup": None, "executionGroups": []})
        write_json(punish_dir / "records.json", records_data)
        write_json(config_dir / "permissions.json", permissions_data)
        write_json(punish_dir / "blacklist.json", blacklist_data)
        print("  无管理组数据，已创建 'default' 配置")
        return

    # 收集所有管理组的群号，用于 records 归属判断
    all_group_sets: dict[str, set[str]] = {}  # name → {admin_group, execution_groups...}

    for g in groups_data:
        name = g.get("name", "")
        if not name:
            continue
        admin = str(g.get("adminGroup", g.get("admin_group", "")))
        execs = g.get("executionGroups", g.get("execution_groups", []))
        if isinstance(execs, list):
            execs = {str(e) for e in execs}
        else:
            execs = set()

        # 构建该管理组包含的所有群号
        group_set = set(execs)
        if admin:
            group_set.add(admin)
        all_group_sets[name] = group_set

        # 写入 groups.json
        config_dir = data / name
        info = {
            "notifyGroup": admin if admin else None,
            "executionGroups": sorted(execs),
        }
        write_json(config_dir / "groups.json", info)

        # 分配 records：from_group 匹配该管理组的群号
        cfg_records = []
        for r in records_data:
            fg = str(r.get("fromGroup", r.get("from_group", "")))
            if fg in group_set:
                cfg_records.append(r)
        punish_dir = config_dir / "punish"
        punish_dir.mkdir(parents=True, exist_ok=True)
        write_json(punish_dir / "records.json", cfg_records)

        # 每配置复制一份 permissions
        write_json(config_dir / "permissions.json", permissions_data)

        # 分配 blacklist：group_name 匹配配置名
        cfg_blacklist = []
        for b in blacklist_data:
            gn = str(b.get("groupName", b.get("group_name", "")))
            if gn == name:
                cfg_blacklist.append(b)
        write_json(punish_dir / "blacklist.json", cfg_blacklist)

        print(f"  配置 '{name}': 通知群={admin or '无'}, "
              f"执行群={len(execs)}个, 记录={len(cfg_records)}条, "
              f"黑名单={len(cfg_blacklist)}条")

    # 处理未归属任何管理组的 records（放入第一个配置）
    leftover_records = []
    for r in records_data:
        fg = str(r.get("fromGroup", r.get("from_group", "")))
        found = False
        for name, gset in all_group_sets.items():
            if fg in gset:
                found = True
                break
        if not found:
            leftover_records.append(r)

    if leftover_records:
        first_name = list(all_group_sets.keys())[0]
        punish_dir = data / first_name / "punish"
        existing = read_json(punish_dir / "records.json") or []
        existing.extend(leftover_records)
        write_json(punish_dir / "records.json", existing)
        print(f"  {len(leftover_records)} 条未归属记录放入配置 '{first_name}'")

    letfover_blacklist = []
    for b in blacklist_data:
        gn = str(b.get("groupName", b.get("group_name", "")))
        if gn not in all_group_sets:
            letfover_blacklist.append(b)

    if letfover_blacklist:
        first_name = list(all_group_sets.keys())[0]
        punish_dir = data / first_name / "punish"
        existing = read_json(punish_dir / "blacklist.json") or []
        existing.extend(letfover_blacklist)
        write_json(punish_dir / "blacklist.json", existing)
        print(f"  {len(letfover_blacklist)} 条未归属黑名单放入配置 '{first_name}'")

    print("=== 迁移完成 ===")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        # 默认 data/ 相对于脚本自身位置：tools/../data
        script_dir = Path(__file__).resolve().parent
        data_dir = str(script_dir.parent / "data")
    migrate(data_dir)
