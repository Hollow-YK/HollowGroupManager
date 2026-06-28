"""
加群审批模块 — 处理群加入请求，支持正则匹配验证信息

独立于进群验证，拥有独立的群开关和审批方案。
审批方案（ApprovalConfig）每配置一份，定义 comment 正则和拒绝原因。
群开关（ApprovalGroupConfig）每群一个，控制是否启用审批。
"""
import html
import logging
import re
import time
from typing import Optional, List, TYPE_CHECKING

from .models import ApprovalConfig, ApprovalGroupConfig

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher

logger = logging.getLogger("Hollow.Approval")

# 审批记录过期时间（秒）— 超时清理避免内存泄漏
_APPROVAL_TTL = 600  # 10 分钟


class ApprovalModule:
    """加群审批 — 正则匹配入群申请"""

    def __init__(self, dispatcher: "CommandDispatcher"):
        self.d = dispatcher
        # config_name → ApprovalConfig
        self._configs: dict[str, ApprovalConfig] = {}
        # config_name → {group_id: ApprovalGroupConfig}
        self._groups: dict[str, dict[str, ApprovalGroupConfig]] = {}
        # (group_id, user_id) → 批准时间戳
        self.approved_users: dict[tuple, float] = {}

        self._load_all()

    def _load_all(self):
        """从所有配置加载审批方案和群开关"""
        for name in self.d.configs:
            # 加载审批方案
            raw_cfg = self.d.dm.load_approval_config(name)
            if raw_cfg:
                try:
                    self._configs[name] = ApprovalConfig.model_validate(raw_cfg)
                except Exception:
                    logger.warning(f"[{name}] verify/approval.json 解析失败")
                    self._configs[name] = ApprovalConfig()
            else:
                self._configs[name] = ApprovalConfig()

            # 加载群开关
            raw_groups = self.d.dm.load_approval_groups(name)
            self._groups[name] = {}
            for gid, v in raw_groups.items():
                try:
                    self._groups[name][gid] = ApprovalGroupConfig.model_validate(v)
                except Exception:
                    self._groups[name][gid] = ApprovalGroupConfig()

    def _save_config(self, config_name: str):
        """保存审批方案"""
        cfg = self._configs.get(config_name)
        if cfg:
            self.d.dm.save_approval_config(
                config_name,
                cfg.model_dump(mode="json", by_alias=True),
            )

    def _save_groups(self, config_name: str):
        """保存指定配置的审批群开关"""
        data = {gid: gcfg.model_dump(mode="json", by_alias=True)
                for gid, gcfg in self._groups.get(config_name, {}).items()}
        self.d.dm.save_approval_groups(config_name, data)

    def _get_group_config(self, group_id: str) -> Optional[ApprovalGroupConfig]:
        """获取群审批开关（取首个匹配的配置）"""
        cfgs = self.d._find_configs(group_id)
        for c in cfgs:
            gcfg = self._groups.get(c.name, {}).get(group_id)
            if gcfg is not None:
                return gcfg
        return None

    def _get_or_create_group_config(self, config_name: str,
                                     group_id: str) -> ApprovalGroupConfig:
        """获取或创建群审批开关"""
        if config_name not in self._groups:
            self._groups[config_name] = {}
        if group_id not in self._groups[config_name]:
            self._groups[config_name][group_id] = ApprovalGroupConfig()
        return self._groups[config_name][group_id]

    def _get_approval_config(self, group_id: str) -> Optional[ApprovalConfig]:
        """获取群所属配置的审批方案"""
        cfgs = self.d._find_configs(group_id)
        for c in cfgs:
            acfg = self._configs.get(c.name)
            if acfg is not None:
                return acfg
        return None

    # ════════════════════════════════════════════════════════════
    # 配置解析
    # ════════════════════════════════════════════════════════════

    def _resolve_group_configs(self, group_id: str, parts: List[str],
                                start_idx: int = 2):
        """解析群对应的配置列表。返回 (configs, error) — 其中之一为 None"""
        cfgs = self.d._find_configs(group_id)
        if not cfgs:
            return None, "该群不在任何配置的执行群中"
        if len(cfgs) == 1:
            return cfgs, None
        cfg_name = parts[start_idx] if len(parts) > start_idx else None
        if cfg_name:
            matched = [c for c in cfgs if c.name == cfg_name]
            if matched:
                return matched, None
            return None, f"配置 '{cfg_name}' 不包含此群"
        names = " / ".join(c.name for c in cfgs)
        return None, f"该群属于多个配置，请指定配置名: {names}"

    def _resolve_single_config(self, group_id: str, parts: List[str],
                                start_idx: int = 2):
        """解析群对应的单个配置。返回 (ConfigState, error) — 其中之一为 None"""
        cfgs, err = self._resolve_group_configs(group_id, parts, start_idx)
        if err:
            return None, err
        assert cfgs is not None
        return cfgs[0], None

    # ════════════════════════════════════════════════════════════
    # 命令处理
    # ════════════════════════════════════════════════════════════

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        """子命令分发: on / off / status / regex / reject"""
        if len(parts) < 2:
            return (
                "用法:\n"
                "  群开关: /ap <on|off|status>\n"
                "  方案设置: /ap <regex|reject|mismatch|welcome> [...]\n"
                "  /ap regex <正则>        匹配正则（空=不校验）\n"
                "  /ap reject <文本>       拒绝原因\n"
                "  /ap mismatch reject|ignore  不匹配时拒绝/忽略\n"
                "  /ap welcome <文本>      入群欢迎消息（空=不发送）"
            )

        sub = parts[1].lower()

        if sub == "on":
            return await self._cmd_on(sender_id, group_id, parts)
        elif sub == "off":
            return await self._cmd_off(sender_id, group_id, parts)
        elif sub == "status":
            return await self._cmd_status(group_id, parts)
        elif sub == "regex":
            return await self._cmd_regex(group_id, parts)
        elif sub == "reject":
            return await self._cmd_reject(group_id, parts)
        elif sub == "mismatch":
            return await self._cmd_mismatch(group_id, parts)
        elif sub == "welcome":
            return await self._cmd_welcome(group_id, parts)
        else:
            return f"未知子命令: {sub}，可选: on / off / status / regex / reject / mismatch / welcome"

    async def _is_group_admin(self, group_id: str, user_id: str) -> bool:
        """检查用户是否为群主或管理员"""
        try:
            members = await self.d.get_member_list(int(group_id))
            if not members:
                return False
            for m in members:
                if str(m.get("user_id", "")) == user_id:
                    role = m.get("role", "")
                    return role in ("owner", "admin")
        except Exception:
            logger.exception("获取群成员列表失败")
        return False

    # ── 群开关命令 ──

    async def _cmd_on(self, sender_id: str, group_id: str,
                      parts: List[str]) -> Optional[str]:
        """开启加群审批"""
        if not await self._is_group_admin(group_id, sender_id):
            return "您不是该群管理员，无法开启加群审批"

        cfgs, err = self._resolve_group_configs(group_id, parts)
        if err:
            return err
        assert cfgs is not None
        cfg = cfgs[0]
        gcfg = self._get_or_create_group_config(cfg.name, group_id)
        if gcfg.enabled:
            return "加群审批已开启"
        gcfg.enabled = True
        self._save_groups(cfg.name)
        return "✅ 已开启加群审批"

    async def _cmd_off(self, sender_id: str, group_id: str,
                       parts: List[str]) -> Optional[str]:
        """关闭加群审批"""
        if not await self._is_group_admin(group_id, sender_id):
            return "您不是该群管理员，无法关闭加群审批"

        cfgs, err = self._resolve_group_configs(group_id, parts)
        if err:
            return err
        assert cfgs is not None
        cfg = cfgs[0]
        gcfg = self._get_or_create_group_config(cfg.name, group_id)
        if not gcfg.enabled:
            return "加群审批未开启"
        gcfg.enabled = False
        self._save_groups(cfg.name)
        return "已关闭加群审批"

    async def _cmd_status(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        """查看加群审批状态"""
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        gcfg = self._get_or_create_group_config(cfg.name, group_id)
        acfg = self._configs.get(cfg.name, ApprovalConfig())

        state = "已开启" if gcfg.enabled else "已关闭"
        regex_info = acfg.comment_regex if acfg.comment_regex else "（不校验，直接同意）"
        mismatch_label = "拒绝" if acfg.on_mismatch == "reject" else "忽略（交管理员审核）"
        welcome_info = acfg.welcome_text if acfg.welcome_text else "（不发送）"
        lines = [
            f"加群审批: {state}",
            f"配置: {cfg.name}",
            f"匹配正则: {regex_info}",
            f"不匹配行为: {mismatch_label}",
            f"拒绝原因: {acfg.reject_reason}",
            f"入群欢迎: {welcome_info}",
        ]
        return "\n".join(lines)

    # ── 方案设置命令 ──

    async def _cmd_regex(self, group_id: str,
                         parts: List[str]) -> Optional[str]:
        """设置入群申请匹配正则: /ap regex <pattern>"""
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        if len(parts) < 3:
            return "用法: /ap regex <正则表达式>  （空字符串=不校验直接同意）"

        pattern = html.unescape(" ".join(parts[2:]))
        acfg = self._configs.get(cfg.name, ApprovalConfig())

        # 验证正则有效性
        if pattern:
            try:
                re.compile(pattern)
            except re.error as e:
                return f"正则表达式无效: {e}"

        acfg.comment_regex = pattern
        self._configs[cfg.name] = acfg
        self._save_config(cfg.name)
        logger.info(f"审批正则已更新: config={cfg.name} regex={pattern!r}")

        if pattern:
            return f"审批正则已设置: {pattern}"
        else:
            return "审批正则已清除（将直接同意所有入群申请）"

    async def _cmd_reject(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        """设置拒绝原因: /ap reject <message>"""
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        if len(parts) < 3:
            return "用法: /ap reject <拒绝原因文本>"

        reason = " ".join(parts[2:])
        acfg = self._configs.get(cfg.name, ApprovalConfig())
        acfg.reject_reason = reason
        self._configs[cfg.name] = acfg
        self._save_config(cfg.name)
        return f"拒绝原因已设置: {reason}"

    async def _cmd_mismatch(self, group_id: str,
                            parts: List[str]) -> Optional[str]:
        """设置不匹配行为: /ap mismatch <reject|ignore>"""
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        if len(parts) < 3 or parts[2].lower() not in ("reject", "ignore"):
            return "用法: /ap mismatch <reject|ignore>\n  reject=不匹配时拒绝  ignore=不匹配时忽略（交管理员审核）"

        mode = parts[2].lower()
        acfg = self._configs.get(cfg.name, ApprovalConfig())
        acfg.on_mismatch = mode
        self._configs[cfg.name] = acfg
        self._save_config(cfg.name)

        label = "拒绝" if mode == "reject" else "忽略（交管理员审核）"
        return f"不匹配行为已设为: {label}"

    async def _cmd_welcome(self, group_id: str,
                           parts: List[str]) -> Optional[str]:
        """设置入群欢迎文本: /ap welcome <text>"""
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        if len(parts) < 3:
            return "用法: /ap welcome <欢迎文本>  （空字符串=不发送）\n占位符: {@新成员} → @新成员"

        text = " ".join(parts[2:])
        acfg = self._configs.get(cfg.name, ApprovalConfig())
        acfg.welcome_text = text
        self._configs[cfg.name] = acfg
        self._save_config(cfg.name)

        if text:
            return f"入群欢迎已设置: {text}"
        else:
            return "入群欢迎已清除"

    # ════════════════════════════════════════════════════════════
    # 事件处理
    # ════════════════════════════════════════════════════════════

    async def on_member_increase(self, event: dict):
        """成员入群 → 若由 Bot 审批且配置了欢迎文本则发送"""
        if event.get("notice_type") != "group_increase":
            return

        group_id = event.get("group_id", 0)
        user_id = event.get("user_id", 0)
        if not group_id or not user_id:
            return

        # 检查是否由 Bot 审批
        if not self.is_bot_approved(int(group_id), int(user_id)):
            return

        # 获取审批方案的欢迎文本
        acfg = self._get_approval_config(str(group_id))
        if not acfg or not acfg.welcome_text:
            return

        # 替换占位符后发送
        text = acfg.welcome_text.replace("{@新成员}", f"[CQ:at,qq={user_id}]")
        try:
            await self.d.send_message(int(group_id), text)
            logger.info(f"已发送入群欢迎: group={group_id} user={user_id}")
        except Exception:
            logger.exception("发送入群欢迎失败")

    async def on_request_group_add(self, event: dict):
        """处理加群请求 — 若该群审批开启则按正则匹配 comment"""
        group_id = event.get("group_id", 0)
        user_id = event.get("user_id", 0)
        sub_type = event.get("sub_type", "add")
        flag = event.get("flag", "")
        comment = event.get("comment", "")

        if not group_id or not user_id or not flag:
            return

        gid_str = str(group_id)
        logger.debug(
            f"收到加群请求: group={group_id} user={user_id} "
            f"comment={comment!r}"
        )

        # 检查审批是否启用
        gcfg = self._get_group_config(gid_str)
        if gcfg is None or not gcfg.enabled:
            return  # 未启用审批，不处理

        # 获取审批方案
        acfg = self._get_approval_config(gid_str)
        if acfg is None:
            acfg = ApprovalConfig()

        logger.debug(
            f"审批匹配: regex={acfg.comment_regex!r} "
            f"comment={comment!r} mismatch={acfg.on_mismatch}"
        )

        # 正则匹配
        if acfg.comment_regex:
            try:
                if not re.search(acfg.comment_regex, comment):
                    # 不匹配 → 按 on_mismatch 决定行为
                    if acfg.on_mismatch == "reject":
                        await self.d._api.set_group_add_request(
                            flag, sub_type, False,
                            reason=acfg.reject_reason,
                        )
                        logger.info(
                            f"加群审批拒绝: group={group_id} user={user_id} "
                            f"comment={comment[:50]}"
                        )
                    else:
                        logger.debug(
                            f"加群审批忽略(不匹配): group={group_id} user={user_id}"
                        )
                    return
            except re.error:
                logger.error(f"审批正则无效: {acfg.comment_regex}")
                return  # 正则坏了，不处理

        # 正则匹配通过（或无需校验）→ 同意
        try:
            ok = await self.d._api.set_group_add_request(
                flag, sub_type, True,
                reason="审批通过",
            )

            if ok:
                self.approved_users[(int(group_id), int(user_id))] = time.time()
                logger.info(
                    f"已自动同意加群请求: group={group_id} user={user_id}"
                )
                self._cleanup_approved()
            else:
                logger.warning(
                    f"加群审批同意失败: group={group_id} user={user_id}"
                )
        except Exception:
            logger.exception("处理加群请求异常")

    def is_bot_approved(self, group_id: int, user_id: int) -> bool:
        """检查用户是否由 Bot 审批入群"""
        key = (group_id, user_id)
        if key in self.approved_users:
            if time.time() - self.approved_users[key] < _APPROVAL_TTL:
                return True
            del self.approved_users[key]
        return False

    def _cleanup_approved(self):
        """清理过期的审批记录"""
        now = time.time()
        expired = [
            k for k, ts in self.approved_users.items()
            if now - ts > _APPROVAL_TTL
        ]
        for k in expired:
            del self.approved_users[k]
