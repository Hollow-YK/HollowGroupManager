"""
指令实现：/help, /p, /rp, /h, /a, /group
"""
import re
import time
import logging
from datetime import datetime
from typing import Optional, List, TYPE_CHECKING

from .models import ManagementGroup, PunishRecord, BlacklistItem
from .data_manager import DataManager
from .render import render_help, render_record_table

if TYPE_CHECKING:
    from bot.api import OneBotAPI

logger = logging.getLogger("Hollow.Cmd")


class CommandHandler:
    """指令处理器"""

    def __init__(self, api: "OneBotAPI", dm: DataManager,
                 wake_words: List[str], super_admins: set[str],
                 render_enabled: bool = True):
        self.api = api
        self.dm = dm
        self.wake_words = wake_words
        self.super_admins = super_admins
        self.render_enabled = render_enabled
        self.primary_wake = wake_words[0] if wake_words else "/"

        # 运行时数据
        self.groups: dict[str, ManagementGroup] = {}
        self.records: List[PunishRecord] = []
        self.records_by_id: dict[int, PunishRecord] = {}
        self.permissions: dict[str, int] = {}
        self.blacklist: List[BlacklistItem] = []
        self._next_rid: int = 1

    # ==================== 生命周期 ====================

    def load(self):
        self.groups = self.dm.load_groups()
        self.records = self.dm.load_records()
        self.permissions = self.dm.load_permissions()
        self.blacklist = self.dm.load_blacklist()

        max_id = 0
        self.records_by_id.clear()
        for r in self.records:
            self.records_by_id[r.id] = r
            if r.id > max_id:
                max_id = r.id
        self._next_rid = max_id + 1
        logger.info(f"已加载: {len(self.groups)}管理组 {len(self.records)}记录 "
                    f"{len(self.permissions)}权限 {len(self.blacklist)}黑名单")

    def save(self):
        self.dm.save_groups(self.groups)
        self.dm.save_records(self.records)
        self.dm.save_permissions(self.permissions)
        self.dm.save_blacklist(self.blacklist)

    # ==================== 权限 ====================

    def _level(self, qq: str) -> int:
        if qq in self.super_admins:
            return 0
        return self.permissions.get(qq, -1)

    # ==================== 查找 ====================

    def _find_group(self, group_id: str) -> Optional[ManagementGroup]:
        for g in self.groups.values():
            if g.admin_group == group_id or group_id in g.execution_groups:
                return g
        return None

    def _find_by_name(self, name: str) -> Optional[ManagementGroup]:
        return self.groups.get(name)

    # ==================== 消息入口 ====================

    async def handle_message(self, event: dict) -> Optional[str]:
        """处理群消息事件，返回回复文本或 None"""
        if event.get("message_type") != "group":
            return None

        raw = event.get("raw_message", event.get("message", "")).strip()
        group_id = str(event.get("group_id", ""))
        sender_id = str(event.get("user_id", ""))

        # 检查唤醒词
        triggered = False
        for w in self.wake_words:
            if raw.startswith(w):
                raw = raw[len(w):].strip()
                triggered = True
                break
        if not triggered:
            return None

        # 权限
        level = self._level(sender_id)
        if level < 0:
            return None

        parts = raw.split()
        if not parts:
            return None
        cmd = parts[0].lower()

        # 从消息中提取 at 列表
        at_list = self._extract_at(event)

        if cmd == "help":
            return await self._help(level, group_id, parts)
        elif cmd == "p":
            return await self._punish(level, sender_id, group_id, parts, at_list)
        elif cmd == "rp":
            return await self._revoke(level, sender_id, group_id, parts)
        elif cmd == "h":
            return await self._query(level, group_id, parts, at_list)
        elif cmd == "a":
            return await self._permission(level, sender_id, group_id, parts, at_list)
        elif cmd == "group":
            return await self._group_cmd(level, sender_id, group_id, parts)

        return None

    async def handle_notice(self, event: dict):
        """处理通知事件（成员入群 → 黑名单检查）"""
        if event.get("notice_type") != "group_increase":
            return

        group_id = str(event.get("group_id", ""))
        user_id = str(event.get("user_id", ""))

        mg = self._find_group(group_id)
        if mg is None:
            return

        matched = None
        for b in self.blacklist:
            if b.qq == int(user_id) and b.group_name == mg.name:
                matched = b
                break

        if matched is None:
            return

        try:
            gid = int(group_id)
            uid = int(user_id)
            ok = await self.api.set_group_kick(gid, uid, reject_add_request=False)
            if not ok:
                logger.error(f"黑名单踢人失败: {user_id}")
                return

            await self.api.send_group_msg(gid,
                f"[CQ:at,qq={user_id}] 在管理组黑名单中，已自动移出。原因：{matched.reason}")
        except Exception as e:
            logger.error(f"黑名单踢人异常: {e}")

    # ==================== 辅助 ====================

    @staticmethod
    def _extract_at(event: dict) -> List[str]:
        """从消息中提取 at 的 QQ 号"""
        ats = []
        # OneBot v11: message 中包含 [CQ:at,qq=xxx]
        raw = event.get("raw_message", event.get("message", ""))
        for m in re.finditer(r'\[CQ:at,qq=(\d+)\]', str(raw)):
            qq = m.group(1)
            if qq and qq != "0":
                ats.append(qq)
        return ats

    @staticmethod
    def _extract_qq(text: str) -> Optional[str]:
        if not text:
            return None
        m = re.search(r'\d{5,}', text)
        return m.group() if m else None

    @staticmethod
    def _parse_duration(dur: str) -> Optional[int]:
        """解析时长 → 秒数"""
        if not dur or not dur.strip():
            return None
        dur = dur.strip()
        try:
            return int(float(dur) * 86400)
        except ValueError:
            pass
        m = re.match(r'^(\d+d)?(\d+h)?(\d+m)?$', dur, re.I)
        if m and dur:
            total = 0
            ok = False
            if m.group(1):
                total += int(m.group(1)[:-1]) * 86400; ok = True
            if m.group(2):
                total += int(m.group(2)[:-1]) * 3600; ok = True
            if m.group(3):
                total += int(m.group(3)[:-1]) * 60; ok = True
            if ok and total > 0:
                return total
        return None

    def _resolve_target(self, at_list: List[str], text: str) -> Optional[str]:
        if at_list:
            return at_list[0]
        return self._extract_qq(text)

    async def _notify_admin(self, mg: Optional[ManagementGroup], msg: str):
        if mg and mg.admin_group:
            try:
                await self.api.send_group_msg(int(mg.admin_group), msg)
            except Exception as e:
                logger.error(f"通知管理群失败: {e}")

    # ==================== 图片渲染（Pillow） ====================

    def _render_png(self, maker) -> Optional[bytes]:
        """调用 Pillow 渲染函数，失败返回 None"""
        if not self.render_enabled:
            return None
        try:
            return maker()
        except ImportError:
            logger.warning("Pillow 未安装，无法渲染图片")
            self.render_enabled = False
            return None
        except Exception as e:
            logger.error(f"渲染图片失败: {e}")
            return None

    async def _send_image(self, group_id: int, png_bytes: bytes):
        """通过 OneBot base64 发送图片"""
        import base64
        b64 = base64.b64encode(png_bytes).decode()
        await self.api.send_group_msg(group_id, f"[CQ:image,file=base64://{b64}]")

    # ==================== /help ====================

    async def _help(self, level: int, group_id: str, parts: List[str]) -> str:
        """渲染帮助图片（Pillow 直接绘制）"""
        w = self.primary_wake
        is_super = (level == 0)
        level_text = f"权限: {level}" + (
            " (超级管理员)" if is_super else " (管理员)" if level == 1 else "")

        if len(parts) < 2:
            lines = self._build_overview_lines(w, is_super)
            title = "HollowGroupManager 帮助"
        else:
            command = parts[1].lower()
            if command not in ("help", "p", "rp", "h", "a", "group"):
                return f"未知命令：{command}，可用：help, p, rp, h, a, group"
            if command in ("a", "group") and not is_super:
                return "此命令仅超级管理员可用"
            lines = self._build_detail_lines(w, command)
            title = f"帮助 — {w}{command}"

        png = self._render_png(lambda: render_help(title, level_text, lines))
        if png:
            await self._send_image(int(group_id), png)
            return ""
        return self._help_fallback_text(w, is_super, parts[1].lower() if len(parts) >= 2 else None)

    def _build_overview_lines(self, w: str, is_super: bool) -> list[str]:
        lines = [
            "# 可用指令", "",
            f"- 用 {w} 表示唤醒词（可在 config.json 中配置）", "",
            f"> {w}help [命令]",
            "- 查看帮助，可指定命令查看详细用法",
            f"~ {w}help p", "",
            f"> {w}p <目标> <方式> [内容] <原因>",
            "- 处罚成员：kick / mute / warn。目标支持 @某人 或 QQ号",
            f"~ {w}p @某人 mute 1d2h 广告", "",
            f"> {w}rp <记录ID> [撤销原因]",
            "- 撤销处罚记录",
            f"~ {w}rp 5 误判", "",
            f"> {w}h [目标] [-i]",
            "- 查询处罚记录，无参数=全组表格，-i=图片表格详情",
            f"~ {w}h  /  {w}h @某人  /  {w}h 123456 -i",
        ]
        if is_super:
            lines += [
                "", f"> {w}a <目标> [1/-1]",
                "- 设置成员权限，1=管理员，-1=普通成员",
                f"~ {w}a @某人 1", "",
                f"> {w}group <子命令>",
                "- 管理组配置：admin / set / remove / info",
                f"~ {w}group admin 反馈组",
            ]
        return lines

    def _build_detail_lines(self, w: str, cmd: str) -> list[str]:
        detail = {
            "help": [f"# {w}help — 查看帮助", f"> {w}help [命令]",
                     f"~ {w}help  → 概览  /  {w}help p  → 详情"],
            "p": [f"# {w}p — 处罚成员", "! 权限：超级管理员 / 管理员",
                  f"> {w}p <目标> <方式> [内容] <原因>",
                  "- <目标>  @某人 或 QQ号",
                  "- <方式>  kick / mute / warn",
                  "- [内容]  kick可选f(黑名单)；mute必填时长；warn不需要",
                  "- <原因>  缺失时记为不合规，不执行",
                  "# 时长格式", "- 纯数字=天  组合 1d2h30m",
                  "# 三步检查", "- 成员在群 → 状态检查 → 执行",
                  f"~ {w}p @某人 mute 1d2h 广告刷屏",
                  f"~ {w}p 123456 kick f 严重违规"],
            "rp": [f"# {w}rp — 撤销处罚", "! 权限：超级管理员 / 管理员",
                   f"> {w}rp <记录ID> [撤销原因]",
                   "! 仅可撤销已执行/执行失败/部分失败的记录",
                   f"~ {w}rp 5  /  {w}rp 5 误判"],
            "h": [f"# {w}h — 查询记录", "! 权限：超级管理员 / 管理员",
                  f"> {w}h [目标] [-i]",
                  "- 无参数  全部记录表格",
                  "- 指定目标  汇总统计",
                  "- -i  图片表格详情",
                  "! 状态颜色：绿已执行 橙已撤销 红失败 灰不合规",
                  f"~ {w}h  /  {w}h @某人  /  {w}h 123456 -i"],
            "a": [f"# {w}a — 设置权限", "! 权限：仅超级管理员",
                  f"> {w}a <目标> [1/-1]",
                  "- 1=管理员(默认)  -1=普通成员",
                  "! 不可设0，不可改自己",
                  f"~ {w}a @某人  /  {w}a 123456 -1"],
            "group": [f"# {w}group — 管理组配置", "! 权限：仅超级管理员",
                      f"> {w}group <子命令>",
                      "- admin <组名>  创建管理组",
                      "- set <组名>  加入为执行群",
                      "- remove  移出管理组",
                      "- info  查看信息",
                      f"~ {w}group admin 反馈组"],
        }
        return detail.get(cmd, [f"未知命令: {cmd}"])

    def _help_fallback_text(self, w: str, is_super: bool, cmd: Optional[str]) -> str:
        if cmd and cmd not in ("help","p","rp","h","a","group"):
            return f"未知命令：{cmd}，可用：help, p, rp, h, a, group"
        lines = [f"=== HollowGroupManager 帮助 ===",
                 f"唤醒词: {', '.join(self.wake_words)}", "",
                 f"{w}help [命令]  查看帮助",
                 f"{w}p <目标> <方式> [内容] <原因>  处罚",
                 f"{w}rp <记录ID> [原因]  撤销",
                 f"{w}h [目标] [-i]  查询"]
        if is_super:
            lines += [f"{w}a <目标> [1/-1]  权限(超管)",
                      f"{w}group <子命令>  管理组(超管)"]
        return "\n".join(lines)

    # ==================== /p 处罚 ====================

    async def _punish(self, level: int, sender_id: str, group_id: str,
                      parts: List[str], at_list: List[str]) -> str:
        if len(parts) < 4:
            return "格式：<唤醒词>p <目标> <方式> [内容] <原因>"

        target_qq = self._resolve_target(at_list, parts[1])
        if not target_qq:
            return "未找到被处罚者QQ，请 @ 或输入QQ号"

        method = parts[2].lower()
        if method not in ("kick", "mute", "warn"):
            return "无效处罚方式，可选：kick, mute, warn"

        content = ""
        if method == "mute":
            if len(parts) < 5:
                return "禁言缺少时长"
            content = parts[3]
            reason_start = 4
            if self._parse_duration(content) is None:
                return "时长格式错误，支持数字(天)或组合如1d2h30m"
        elif method == "kick":
            if len(parts) >= 4 and parts[3].lower() == "f":
                content = "f"; reason_start = 4
            else:
                content = ""; reason_start = 3
        else:
            content = ""; reason_start = 3

        if reason_start >= len(parts):
            r = self._add_record(sender_id, group_id, int(target_qq),
                                 method, content, "", "不合规")
            mg = self._find_group(group_id)
            await self._notify_admin(mg,
                f"[不合规] 处罚（{r.id}）：发起者（{sender_id}）在群（{group_id}）"
                f"发起的处罚缺少原因，未执行。")
            self.save()
            return "原因缺失，已记录为[不合规]，未执行处罚。"

        reason = " ".join(parts[reason_start:])

        mg = self._find_group(group_id)
        if mg is None:
            return "当前群不属于任何管理组，无法执行。"

        r = self._add_record(sender_id, group_id, int(target_qq),
                             method, content, reason, "执行中")

        gid_int = int(group_id)
        tid_int = int(target_qq)
        any_ok = False
        any_fail = False
        fail_groups: List[str] = []

        for eg in list(mg.execution_groups):
            eg_int = int(eg)
            # 第一步
            if not await self.api.is_member_in_group(eg_int, tid_int):
                continue
            # 第二步
            if method == "mute":
                muted = await self.api.get_muted_members(eg_int)
                for mm in muted:
                    if mm["user_id"] == tid_int:
                        await self._notify_admin(mg,
                            f"[提示] 处罚「{r.id}」在群{eg}成员{target_qq}已被禁言，将更新时长。")
                        break
            # 第三步
            try:
                if method == "kick":
                    ok = await self.api.set_group_kick(eg_int, tid_int,
                                                       content == "f")
                    if not ok:
                        raise RuntimeError("踢出返回失败")
                    if content == "f":
                        self._blacklist_add(tid_int, reason, mg.name)
                    any_ok = True
                elif method == "mute":
                    sec = self._parse_duration(content)
                    ok = await self.api.set_group_ban(eg_int, tid_int, sec)
                    if not ok:
                        raise RuntimeError("禁言返回失败")
                    any_ok = True
                else:
                    any_ok = True
            except Exception as e:
                any_fail = True
                fail_groups.append(eg)
                await self._notify_admin(mg,
                    f"[异常] 处罚「{r.id}」在群{eg}执行失败：{e}")

        if any_fail and not any_ok:
            r.status = "执行失败"
            r.fail_detail = "失败群：" + ",".join(fail_groups)
        elif any_fail:
            r.status = "部分失败"
            r.fail_detail = "失败群：" + ",".join(fail_groups)
        else:
            r.status = "已执行"

        if any_fail and not any_ok:
            fb = "处罚执行失败，失败群：" + ",".join(fail_groups)
        elif any_fail:
            fb = "处罚部分失败，失败群：" + ",".join(fail_groups)
        else:
            fb = "处罚已执行。"

        await self._notify_admin(mg,
            f"处罚「{r.id}」：{sender_id}在{group_id}发起对"
            f"{target_qq}的「{r.describe()}」处罚，原因：「{reason}」，"
            f"状态：{r.status}" +
            (f"（{r.fail_detail}）" if r.fail_detail else ""))

        self.save()
        return fb

    # ==================== /rp 撤销 ====================

    async def _revoke(self, level: int, sender_id: str, group_id: str,
                      parts: List[str]) -> str:
        if len(parts) < 2:
            return "格式：/rp <记录ID> [撤销原因]"
        try:
            rid = int(parts[1])
        except ValueError:
            return "记录ID必须为数字"

        target = self.records_by_id.get(rid)
        if target is None:
            return "记录不存在"
        if target.status not in ("已执行", "执行失败", "部分失败"):
            return f"状态为 {target.status}，不可撤销"

        rr = " ".join(parts[2:]) if len(parts) >= 3 else ""
        mg = self._find_group(target.from_group)
        if mg is None:
            return "记录对应管理组异常"

        any_ok = False
        skip: List[str] = []
        fail: List[str] = []

        if target.method == "mute":
            for eg in list(mg.execution_groups):
                eg_int = int(eg); tid_int = target.target
                try:
                    if not await self.api.is_member_in_group(eg_int, tid_int):
                        skip.append(f"{eg}(成员不存在)"); continue
                    ok = await self.api.set_group_ban(eg_int, tid_int, 0)
                    if ok:
                        any_ok = True
                    else:
                        fail.append(eg)
                except Exception as e:
                    fail.append(eg)
                    await self._notify_admin(mg,
                        f"[异常] 撤销（{target.id}）在群（{eg}）失败：{e}")
            if not any_ok and fail:
                return "撤销失败，失败群：" + ",".join(fail)

        elif target.method == "kick" and target.content == "f":
            self._blacklist_remove(target.target, mg.name)
            any_ok = True

        target.status = "已撤销"
        target.revoke_time = int(time.time())
        target.revoke_reason = rr

        msg = f"记录 {rid} 已撤销"
        if skip:
            msg += "（跳过：" + ", ".join(skip) + "）"

        await self._notify_admin(mg,
            f"[撤销] 处罚（{target.id}）已被（{sender_id}）撤销，"
            f"原处罚：（{target.target}）的（{target.describe()}），"
            f"原因：（{target.reason}）。撤销原因：" + (rr or "无"))

        self.save()
        return msg

    # ==================== /h 查询 ====================

    async def _query(self, level: int, group_id: str,
                     parts: List[str], at_list: List[str]) -> str:
        mg = self._find_group(group_id)
        if mg is None:
            return "当前群不属于管理组"

        all_in_group = [r for r in self.records
                        if r.from_group == group_id
                        or r.from_group in mg.execution_groups
                        or mg.admin_group == r.from_group]

        if len(parts) < 2:
            return await self._render_table(all_in_group, group_id)

        target_qq = self._resolve_target(at_list, parts[1])
        if not target_qq:
            return "未找到目标QQ"

        tid = int(target_qq)
        filtered = [r for r in all_in_group if r.target == tid]
        detail = len(parts) > 2 and parts[2] == "-i"

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
                        s = self._parse_duration(r.content)
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
        if not records:
            return "无记录"

        png = self._render_png(lambda: render_record_table(records))
        if png:
            await self._send_image(int(group_id), png)
            return ""

        # 回退纯文本
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

    # ==================== /a 权限 ====================

    async def _permission(self, level: int, sender_id: str, group_id: str,
                          parts: List[str], at_list: List[str]) -> str:
        if level != 0:
            return "仅超级管理员可用"
        if len(parts) < 2:
            return "格式：/a <成员> [1/-1]"

        tqq = self._resolve_target(at_list, parts[1])
        if not tqq:
            return "未找到目标QQ"
        if tqq == sender_id:
            return "不能修改自己的权限"

        nl = 1
        if len(parts) >= 3:
            try:
                nl = int(parts[2])
            except ValueError:
                return "权限只能是1或-1"
        if nl not in (1, -1):
            return "权限只能是1或-1"

        self.permissions[tqq] = nl
        self.save()
        return f"已设置 {tqq} 为{'管理员' if nl == 1 else '普通成员'}"

    # ==================== /group 管理组 ====================

    async def _group_cmd(self, level: int, sender_id: str, group_id: str,
                         parts: List[str]) -> str:
        if level != 0:
            return "仅超级管理员可用"
        if len(parts) < 2:
            return "子命令：admin <名称> / set <名称> / remove / info"

        sub = parts[1].lower()
        if sub == "admin":
            if len(parts) < 3:
                return "格式：/group admin <组名>"
            name = parts[2]
            if self._find_by_name(name):
                return "管理组已存在"
            if self._find_group(group_id):
                return "本群已属于其他管理组"
            mg = ManagementGroup(name=name, admin_group=group_id)
            self.groups[name] = mg
            self.save()
            return f"管理组 \"{name}\" 创建成功，本群为管理群"

        elif sub == "set":
            if len(parts) < 3:
                return "格式：/group set <组名>"
            name = parts[2]
            exist = self._find_by_name(name)
            if not exist:
                return "管理组不存在"
            if exist.admin_group == group_id:
                return "管理群不能作为执行群"
            if self._find_group(group_id):
                return "本群已属于其他管理组"
            exist.execution_groups.add(group_id)
            self.save()
            return f"已将本群加入管理组 \"{name}\" 作为执行群"

        elif sub == "remove":
            cur = self._find_group(group_id)
            if not cur:
                return "本群不属于任何管理组"
            if cur.admin_group == group_id:
                return "管理群无法移出，请用 /group admin 重建"
            cur.execution_groups.discard(group_id)
            self.save()
            return "已从管理组移出"

        elif sub == "info":
            info = self._find_group(group_id)
            if not info:
                return "本群未加入管理组"
            role = "管理群" if info.admin_group == group_id else "执行群"
            el = ",".join(sorted(info.execution_groups)) if info.execution_groups else "无"
            return (f"组名：{info.name}\n角色：{role}\n"
                    f"管理群：{info.admin_group}\n执行群列表：{el}")
        return "未知子命令"

    # ==================== 记录/黑名单操作 ====================

    def _add_record(self, sender: str, from_group: str, target: int,
                    method: str, content: str, reason: str, status: str) -> PunishRecord:
        r = PunishRecord(id=self._next_rid, sender=int(sender),
                         time=int(time.time()), from_group=from_group,
                         target=target, method=method, content=content,
                         reason=reason, status=status)
        self._next_rid += 1
        self.records.append(r)
        self.records_by_id[r.id] = r
        return r

    def _blacklist_add(self, qq: int, reason: str, group_name: str):
        for b in self.blacklist:
            if b.qq == qq and b.group_name == group_name:
                return
        self.blacklist.append(BlacklistItem(
            qq=qq, reason=reason, add_time=int(time.time()),
            group_name=group_name))

    def _blacklist_remove(self, qq: int, group_name: str):
        self.blacklist = [b for b in self.blacklist
                          if not (b.qq == qq and b.group_name == group_name)]
