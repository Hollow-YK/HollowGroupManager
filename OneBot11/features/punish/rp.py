"""
/rp 指令 — 撤销处罚。

可撤销已执行/执行失败/部分失败的记录。
撤销禁言 = 解除禁言，撤销踢出(f) = 移除黑名单。
"""
import time
import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher

logger = logging.getLogger("Hollow.Cmd")


class RpModule:
    """撤销处罚指令模块。"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: list, at_list: list, sender_card: str = "") -> Optional[str]:
        if len(parts) < 2:
            return "格式：/rp [配置] <记录ID> [撤销原因]"

        match_cfgs = self.d._find_configs(group_id)
        if not match_cfgs:
            return None

        # 解析配置名
        cfg_name: Optional[str] = None
        id_idx = 1
        cfg = self.d._get_config(parts[1])
        if cfg is not None:
            cfg_name = parts[1]
            id_idx = 2
        elif len(match_cfgs) >= 2:
            return "本群属于多个配置，请指定配置名称：/rp <配置名称> <记录ID> [撤销原因]"

        if id_idx >= len(parts):
            return "缺少记录ID"

        try:
            rid = int(parts[id_idx])
        except ValueError:
            return "记录ID必须为数字"

        # 查找记录
        rr = " ".join(parts[id_idx + 1:])

        if cfg_name:
            target_cfg = self.d._get_config(cfg_name)
            if target_cfg is None:
                return f"配置 \"{cfg_name}\" 不存在"
            target = target_cfg.records_by_id.get(rid)
            if target is None:
                return f"配置 \"{cfg_name}\" 中不存在记录 {rid}"
            cfgs_to_search = [target_cfg]
        else:
            target = None
            cfgs_to_search = match_cfgs
            for c in cfgs_to_search:
                target = c.records_by_id.get(rid)
                if target is not None:
                    break

        if target is None:
            return "记录不存在"

        # 找到记录所属配置
        owner_cfg = None
        for c in self.d.configs.values():
            if rid in c.records_by_id:
                owner_cfg = c
                break

        if owner_cfg is None:
            return "记录对应配置异常"

        if target.status not in ("已执行", "执行失败", "部分失败"):
            return f"状态为 {target.status}，不可撤销"

        any_ok = False
        skip: list[str] = []
        fail: list[str] = []

        if target.method == "mute":
            for eg in list(owner_cfg.info.execution_groups):
                eg_int = int(eg)
                tid_int = target.target
                try:
                    if not await self.d.is_member_in_group(eg_int, tid_int):
                        skip.append(f"{eg}(成员不存在)")
                        continue
                    ok = await self.d.unban(eg_int, tid_int)
                    if ok:
                        any_ok = True
                    else:
                        fail.append(eg)
                except Exception as e:
                    fail.append(eg)
                    await self.d._notify_admin(owner_cfg,
                        f"[异常] 撤销（{target.id}）在群（{eg}）失败：{e}")
            if not any_ok and fail:
                return "撤销失败，失败群：" + ",".join(fail)
        elif target.method == "kick" and target.content == "f":
            self.d._blacklist_remove(owner_cfg.name, target.target, owner_cfg.name)
            any_ok = True

        target.status = "已撤销"
        target.revoke_time = int(time.time())
        target.revoke_reason = rr

        msg = f"记录 {rid} 已撤销"
        if skip:
            msg += "（跳过：" + ", ".join(skip) + "）"

        await self.d._notify_admin(owner_cfg,
            f"[撤销] 处罚（{target.id}）已被（{sender_id}）撤销，"
            f"原处罚：（{target.target}）的（{target.describe()}），"
            f"原因：（{target.reason}）。撤销原因：" + (rr or "无"))

        self.d.save()
        return msg
