"""
加群审批模块 — 处理群加入请求，支持正则匹配验证信息

独立于进群验证，拥有独立的群开关和审批方案。
审批方案（ApprovalConfig）每配置一份，定义 comment 正则和拒绝原因。
群开关（ApprovalGroupConfig）每群一个，控制是否启用审批。
"""
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

# ApprovalConfig 字段映射：命令名 → (模型属性, 类型, 描述)
_APPROVAL_CONFIG_FIELDS: dict[str, tuple[str, type, str]] = {}

def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])

_approval_field_specs: list[tuple[str, type, str]] = [
    ("comment_regex",  str, "匹配正则（空=不校验直接同意）"),
    ("reject_reason",  str, "拒绝原因文本"),
    ("on_mismatch",    str, "不匹配行为: reject=拒绝, ignore=忽略"),
    ("welcome_text",   str, "入群欢迎消息（空=不发送）"),
]

for _attr, _typ, _desc in _approval_field_specs:
    _APPROVAL_CONFIG_FIELDS[_attr] = (_attr, _typ, _desc)
    _APPROVAL_CONFIG_FIELDS[_snake_to_camel(_attr)] = (_attr, _typ, _desc)


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
                "  配置: /ap config [key] [value]\n"
                "  /ap config comment_regex <正则>    匹配正则（空=不校验）\n"
                "  /ap config reject_reason <文本>    拒绝原因\n"
                "  /ap config on_mismatch reject|ignore  不匹配时拒绝/忽略\n"
                "  /ap config welcome_text <文本>     入群欢迎消息（空=不发送）"
            )

        sub = parts[1].lower()

        if sub == "on":
            return await self._cmd_on(sender_id, group_id, parts)
        elif sub == "off":
            return await self._cmd_off(sender_id, group_id, parts)
        elif sub == "status":
            return await self._cmd_status(group_id, parts)
        elif sub == "config":
            return await self._cmd_config(group_id, parts)
        else:
            return f"未知子命令: {sub}，可选: on / off / status / config"

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
        reject_info = acfg.reject_reason if acfg.reject_reason else "（默认）"
        lines = [
            f"加群审批: {state}",
            f"配置: {cfg.name}",
            f"匹配正则 (comment_regex): {regex_info}",
            f"不匹配行为 (on_mismatch): {mismatch_label}",
            f"拒绝原因 (reject_reason): {reject_info}",
            f"入群欢迎 (welcome_text): {welcome_info}",
        ]
        return "\n".join(lines)

    # ── 统一配置命令 ──

    async def _cmd_config(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        """统一配置管理: /ap config [key] [value]"""
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=2)
        if err:
            return err
        assert cfg is not None

        acfg = self._configs.get(cfg.name, ApprovalConfig())

        # 确定 key/value 起始位置
        key_start = 3 if (len(parts) > 2 and parts[2] == cfg.name) else 2

        # 无参数 → 列出所有字段
        if len(parts) <= key_start:
            lines = [f"审批方案配置 ({cfg.name}):"]
            for attr, typ, desc in _approval_field_specs:
                raw = getattr(acfg, attr)
                if attr == "on_mismatch":
                    display = raw  # reject / ignore
                else:
                    display = raw if raw else "（空）"
                lines.append(f"  {attr} = {display}")
            lines.append("")
            lines.append("修改: /ap config <key> <value>")
            lines.append("可用 key: " + ", ".join(a for a, _, _ in _approval_field_specs))
            return "\n".join(lines)

        key = parts[key_start].lower()
        field = _APPROVAL_CONFIG_FIELDS.get(key)
        if field is None:
            available = ", ".join(sorted(set(
                a for a, _, _ in _approval_field_specs
            )))
            return f"未知配置项: {key}\n可用: {available}\n也支持 camelCase（如 commentRegex）和旧命令名（如 regex）"

        attr, typ, desc = field

        # 单参数 → 获取值
        if len(parts) <= key_start + 1:
            raw = getattr(acfg, attr)
            if attr == "on_mismatch":
                display = raw
            else:
                display = raw if raw else "（空）"
            camel = _snake_to_camel(attr)
            return f"{attr} ({camel}): {display}\n说明: {desc}"

        # 多参数 → 设置值
        value = " ".join(parts[key_start + 1:])

        if attr == "on_mismatch":
            value_lower = value.strip().lower()
            if value_lower not in ("reject", "ignore"):
                return "on_mismatch 只能设为: reject 或 ignore"
            acfg.on_mismatch = value_lower
            display = value_lower
        else:
            acfg.__setattr__(attr, value)
            display = value if value else "（空）"

        # on_mismatch regex 额外验证
        if attr == "comment_regex" and value:
            import re as _re
            try:
                _re.compile(value)
            except _re.error as e:
                return f"正则表达式无效: {e}"

        self._configs[cfg.name] = acfg
        self._save_config(cfg.name)
        return f"{attr} 已设为: {display}"

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
