"""
/h 指令 — 查询处罚记录。

支持：全部记录表格、指定成员统计、-i 图片详情。
"""
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from core.models import PunishRecord
from features.render import render_record_table

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher


class HistoryModule:
    """查询记录指令模块。"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        match_cfgs = self.d._find_configs(group_id)
        if not match_cfgs:
            return None

        # 解析配置名
        cfg_name: Optional[str] = None
        rest_start = 1
        cfg = self.d._get_config(parts[1]) if len(parts) > 1 else None
        if cfg is not None:
            cfg_name = parts[1]
            rest_start = 2
        elif len(match_cfgs) >= 2:
            return "本群属于多个配置，请指定配置名称：/h <配置名称> [QQ用户] [-i]"

        # 确定查询的配置
        if cfg_name:
            target_cfgs = [c for c in match_cfgs if c.name == cfg_name]
            if not target_cfgs:
                return f"配置 \"{cfg_name}\" 不存在或不包含本群"
        else:
            target_cfgs = match_cfgs

        # 收集记录
        all_records: list[PunishRecord] = []
        for c in target_cfgs:
            all_records.extend(c.records)

        # 无参数 → 全表
        if len(parts) < rest_start + 1:
            return await self._render_table(all_records, group_id)

        # 解析目标
        target_qq = self.d._resolve_target(at_list, parts[rest_start])
        if not target_qq:
            # 可能是 -i（无目标的详情）
            if parts[rest_start] == "-i":
                return await self._render_table(all_records, group_id)
            return "未找到目标QQ"

        tid = int(target_qq)
        filtered = [r for r in all_records if r.target == tid]
        detail = len(parts) > rest_start + 1 and parts[rest_start + 1] == "-i"

        if detail:
            return await self._render_table(filtered, group_id)
        else:
            total = kick = mute_n = 0
            mute_sec = 0
            for r in filtered:
                if r.status in ("已执行", "执行失败", "部分失败"):
                    total += 1
                    if r.method == "mute":
                        mute_n += 1
                        s = self.d._parse_duration(r.content)
                        if s:
                            mute_sec += s
                    elif r.method == "kick":
                        kick += 1
            lines = [f"成员 {target_qq} 统计："]
            if total > 0:
                lines.append(f"被处罚总次数：{total}")
            if mute_n > 0:
                lines.append(f"被禁言次数：{mute_n}")
                d = mute_sec // 86400
                h = (mute_sec % 86400) // 3600
                m = (mute_sec % 3600) // 60
                lines.append(f"被禁言总时长：{d}d{h}h{m}m")
            if kick > 0:
                lines.append(f"被踢次数：{kick}")
            if total == 0:
                lines.append("暂无记录")
            return "\n".join(lines)

    async def _render_table(self, records: List[PunishRecord], group_id: str) -> str:
        """渲染记录表格（Pillow 优先，纯文本回退）"""
        if not records:
            return "无记录"

        png = self.d._render_png(lambda: render_record_table(records))
        if png:
            await self.d.send_image(int(group_id), png)
            return ""

        fmt = "%m-%d %H:%M"
        lines = ["记录列表：",
                 "ID | 时间 | 发起群 | 发起者 | 方式 | 内容 | 原因 | 状态 | 撤销时间 | 撤销原因"]
        for r in records:
            c = r.content or "-"
            rr = r.revoke_reason or "-"
            fg = r.from_group or "-"
            m = r.method or "-"
            rs = r.reason or "-"
            st = r.status or "-"
            rt = datetime.fromtimestamp(r.revoke_time).strftime(fmt) if r.revoke_time else "-"
            ts = datetime.fromtimestamp(r.time).strftime(fmt) if r.time else "-"
            lines.append(f"{r.id} | {ts} | {fg} | {r.sender} | {m} | {c} | {rs} | {st} | {rt} | {rr}")
        return "\n".join(lines)
