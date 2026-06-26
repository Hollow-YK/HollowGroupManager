"""
/p 指令 — 处罚执行 + 黑名单入群自动踢人。

处罚方式：kick（踢出）、mute（禁言）、warn（警告）。
kick 可选 f 标记加入黑名单。
"""
import logging
from typing import Optional, List, TYPE_CHECKING

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher

logger = logging.getLogger("Hollow.Cmd")

VALID_METHODS = ("kick", "mute", "warn")


class PunishModule:
    """处罚指令模块。"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    # ========== 指令入口 ==========

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        if len(parts) < 2:
            return "格式：<唤醒词>p <目标> [配置] <方式> [内容] <原因>"

        # 解析目标
        target_qq = self.d._resolve_target(at_list, parts[1])
        if not target_qq:
            return "未找到被处罚者QQ，请 @ 或输入QQ号"

        # 尝试解析配置名（parts[2] 若不是方式则视为配置名）
        cfg_name: Optional[str] = None
        method_idx = 2
        if len(parts) > 2 and parts[2].lower() not in VALID_METHODS:
            cfg_name = parts[2]
            method_idx = 3

        # 确定配置范围
        match_cfgs = self.d._find_configs(group_id)
        if not match_cfgs:
            return None  # 不响应

        if cfg_name:
            target_cfgs = [c for c in match_cfgs if c.name == cfg_name]
            if not target_cfgs:
                return f"配置 \"{cfg_name}\" 不存在或不包含本群"
        else:
            target_cfgs = match_cfgs

        # 解析方式和内容
        if method_idx >= len(parts):
            return "缺少处罚方式（kick / mute / warn）"
        method = parts[method_idx].lower()
        if method not in VALID_METHODS:
            return "无效处罚方式，可选：kick, mute, warn"

        content = ""
        reason_start = method_idx + 1
        if method == "mute":
            if len(parts) < method_idx + 2:
                return "禁言缺少时长"
            content = parts[method_idx + 1]
            reason_start = method_idx + 2
            if self.d._parse_duration(content) is None:
                return "时长格式错误，支持数字(天)或组合如1d2h30m"
        elif method == "kick":
            if len(parts) > method_idx + 1 and parts[method_idx + 1].lower() == "f":
                content = "f"
                reason_start = method_idx + 2
            else:
                reason_start = method_idx + 1

        # 原因检查
        if reason_start >= len(parts):
            # 不合规
            records_info = []
            for cfg in target_cfgs:
                r = self.d._add_record(cfg.name, sender_id, group_id, int(target_qq),
                                       method, content, "", "不合规")
                records_info.append((cfg, r))
                await self.d._notify_admin(cfg,
                    f"[不合规] 处罚（{r.id}）：发起者（{sender_id}）在群（{group_id}）"
                    f"发起的处罚缺少原因，未执行。")
            self.d.save()
            return "原因缺失，已记录为[不合规]，未执行处罚。"

        reason = " ".join(parts[reason_start:])

        # 收集执行群（去重）
        all_exec_groups: set[str] = set()
        for cfg in target_cfgs:
            all_exec_groups.update(cfg.info.execution_groups)

        gid_int = int(group_id)
        tid_int = int(target_qq)

        # 创建记录
        records_info: list = []
        for cfg in target_cfgs:
            r = self.d._add_record(cfg.name, sender_id, group_id, tid_int,
                                   method, content, reason, "执行中")
            records_info.append((cfg, r))

        # 执行处罚
        any_ok = False
        any_fail = False
        fail_groups: List[str] = []

        for eg in list(all_exec_groups):
            eg_int = int(eg)
            if not await self.d.is_member_in_group(eg_int, tid_int):
                continue
            if method == "mute":
                muted = await self.d.get_muted_members(eg_int)
                for mm in muted:
                    if mm["user_id"] == tid_int:
                        for cfg, r in records_info:
                            await self.d._notify_admin(cfg,
                                f"[提示] 处罚「{r.id}」在群{eg}成员{target_qq}已被禁言，将更新时长。")
                        break
            try:
                if method == "kick":
                    ok = await self.d.kick(eg_int, tid_int, content == "f")
                    if not ok:
                        raise RuntimeError("踢出返回失败")
                    if content == "f":
                        for cfg in target_cfgs:
                            self.d._blacklist_add(cfg.name, tid_int, reason, cfg.name)
                    any_ok = True
                elif method == "mute":
                    sec = self.d._parse_duration(content)
                    ok = await self.d.ban(eg_int, tid_int, sec)
                    if not ok:
                        raise RuntimeError("禁言返回失败")
                    any_ok = True
                else:
                    any_ok = True
            except Exception as e:
                any_fail = True
                fail_groups.append(eg)
                for cfg, r in records_info:
                    await self.d._notify_admin(cfg,
                        f"[异常] 处罚「{r.id}」在群{eg}执行失败：{e}")

        # 更新状态
        fail_str = "失败群：" + ",".join(fail_groups) if fail_groups else ""
        for cfg, r in records_info:
            if any_fail and not any_ok:
                r.status = "执行失败"
                r.fail_detail = fail_str
            elif any_fail:
                r.status = "部分失败"
                r.fail_detail = fail_str
            else:
                r.status = "已执行"

        # 通知
        notified: set[str] = set()
        for cfg, r in records_info:
            ng = cfg.info.notify_group
            if ng and ng not in notified:
                notified.add(ng)
                fb = "处罚已执行。" if not fail_str else f"处罚部分失败（{fail_str}）"
                if any_fail and not any_ok:
                    fb = f"处罚执行失败（{fail_str}）"
                try:
                    await self.d.send_message(int(ng),
                        f"处罚「{r.id}」：{sender_id}在{group_id}发起对"
                        f"{target_qq}的「{r.describe()}」处罚，原因：「{reason}」，"
                        f"状态：{r.status}" +
                        (f"（{r.fail_detail}）" if r.fail_detail else ""))
                except Exception:
                    pass

        self.d.save()

        if any_fail and not any_ok:
            return f"处罚执行失败，{fail_str}"
        elif any_fail:
            return f"处罚部分失败，{fail_str}"
        return f"处罚已执行。（{len(target_cfgs)} 配置）"

    # ========== 事件监听：黑名单入群自动踢人 ==========

    async def on_member_join(self, event: dict) -> None:
        """监听 notice.group_increase → 检查黑名单 → 自动踢出"""
        if event.get("notice_type") != "group_increase":
            return

        group_id = str(event.get("group_id", ""))
        user_id = str(event.get("user_id", ""))

        configs = self.d._find_configs(group_id)
        if not configs:
            return

        uid = int(user_id)
        kicked = False
        for cfg in configs:
            for b in cfg.blacklist:
                if b.qq == uid and b.group_name == cfg.name:
                    try:
                        gid = int(group_id)
                        ok = await self.d.kick(gid, uid, reject_add=False)
                        if ok:
                            await self.d.send_message(gid, [
                                {"type": "at", "data": {"qq": user_id}},
                                {"type": "text", "data": {
                                    "text": f" 在配置 {cfg.name} 黑名单中，已自动移出。原因：{b.reason}"
                                }},
                            ])
                            kicked = True
                    except Exception as e:
                        logger.error(f"黑名单踢人异常: {e}")
                    break
            if kicked:
                break
