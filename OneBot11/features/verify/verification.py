"""
进群验证模块 — 新成员入群后多模式答题验证

验证方案直接属于每个 Config（无预设概念），各群独立开关。
非 Bot 审批入群的成员可设置独立超时时间。
"""
import asyncio
import logging
import random
import re
import secrets
import time
from typing import Optional, List, Dict, TYPE_CHECKING

from features.render import render_verify_guide, render_question_card

from .models import (
    Block, BlockType, Question, VerifyConfig, VerifyGroupConfig,
    QuestionInstance, BlockSession, VerifySession,
)

if TYPE_CHECKING:
    from core.dispatcher import CommandDispatcher
    from .approval import ApprovalModule

logger = logging.getLogger("Hollow.Verify")

# 答案字符串最大长度（防止过长消息）
_MAX_ANSWER_LEN = 200


class VerificationModule:
    """进群验证"""

    def __init__(self, dispatcher: "CommandDispatcher",
                 approval_module: "ApprovalModule"):
        self.d = dispatcher
        self.ap = approval_module
        # config_name → VerifyConfig
        self._configs: dict[str, VerifyConfig] = {}
        # config_name → {group_id: VerifyGroupConfig}
        self._groups: dict[str, dict[str, VerifyGroupConfig]] = {}
        # (group_id, user_id) → VerifySession
        self.sessions: dict[tuple, VerifySession] = {}
        self._self_id: Optional[int] = None  # 机器人自身 QQ

        self._load_all()

    def _load_all(self):
        """从所有配置加载验证方案和群开关"""
        for name in self.d.configs:
            # 加载验证方案
            raw_cfg = self.d.dm.load_verify_config(name)
            if raw_cfg:
                try:
                    self._configs[name] = VerifyConfig.model_validate(raw_cfg)
                except Exception:
                    logger.warning(f"[{name}] verify/verify.json 解析失败，使用默认配置")
                    self._configs[name] = VerifyConfig()
            else:
                self._configs[name] = VerifyConfig()

            # 加载群开关
            raw_groups = self.d.dm.load_verify_groups(name)
            self._groups[name] = {}
            for gid, v in raw_groups.items():
                try:
                    self._groups[name][gid] = VerifyGroupConfig.model_validate(v)
                except Exception:
                    self._groups[name][gid] = VerifyGroupConfig()

    def _save_config(self, config_name: str):
        """保存验证方案"""
        cfg = self._configs.get(config_name)
        if cfg:
            self.d.dm.save_verify_config(
                config_name,
                cfg.model_dump(mode="json", by_alias=True),
            )

    def _save_groups(self, config_name: str):
        """保存群验证开关"""
        data = {
            gid: gcfg.model_dump(mode="json", by_alias=True)
            for gid, gcfg in self._groups.get(config_name, {}).items()
        }
        self.d.dm.save_verify_groups(config_name, data)

    def _get_verify_config(self, group_id: str) -> Optional[VerifyConfig]:
        """获取群所属配置的验证方案"""
        cfgs = self.d._find_configs(group_id)
        for c in cfgs:
            vcfg = self._configs.get(c.name)
            if vcfg is not None:
                return vcfg
        return None

    def _get_config_name(self, group_id: str) -> Optional[str]:
        """获取群所属配置名（首个匹配）"""
        cfgs = self.d._find_configs(group_id)
        if cfgs:
            return cfgs[0].name
        return None

    def _get_or_create_group_config(self, config_name: str,
                                     group_id: str) -> VerifyGroupConfig:
        """获取或创建群验证开关"""
        if config_name not in self._groups:
            self._groups[config_name] = {}
        if group_id not in self._groups[config_name]:
            self._groups[config_name][group_id] = VerifyGroupConfig()
        return self._groups[config_name][group_id]

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

    # ════════════════════════════════════════════════════════════
    # 命令处理
    # ════════════════════════════════════════════════════════════

    async def handle(self, level: int, sender_id: str, group_id: str,
                     parts: List[str], at_list: List[str],
                     sender_card: str = "") -> Optional[str]:
        """子命令分发"""
        if len(parts) < 2:
            return self._usage()

        sub = parts[1].lower()

        # 群级开关命令
        if sub == "on":
            return await self._cmd_on(sender_id, group_id, parts)
        elif sub == "off":
            return await self._cmd_off(sender_id, group_id, parts)
        elif sub == "status":
            return await self._cmd_status(group_id, parts)
        # 方案设置命令
        elif sub == "welcome":
            return await self._cmd_welcome(group_id, parts)
        elif sub == "maxerr":
            return await self._cmd_maxerr(group_id, parts)
        elif sub == "retry":
            return await self._cmd_retry(group_id)
        elif sub == "timeout":
            return await self._cmd_timeout(group_id, parts)
        elif sub == "bottimeout":
            return await self._cmd_bottimeout(group_id, parts)
        # 考核块命令
        elif sub == "block":
            return await self._cmd_block(group_id, parts)
        # 题目命令
        elif sub == "question":
            return await self._cmd_question(group_id, parts)
        else:
            return f"未知子命令: {sub}\n{self._usage()}"

    def _usage(self) -> str:
        return (
            "用法:\n"
            "  群开关: /v <on|off|status>\n"
            "  方案设置: /v <welcome|maxerr|retry|timeout> [...]\n"
            "  考核块: /v block <add|remove|list|move|edit> [...]\n"
            "  题目: /v question <add|remove|list|edit> [...]"
        )

    def _resolve_single_config(self, group_id: str, parts: List[str],
                                start_idx: int = 2):
        """解析群对应的单个配置。返回 (ConfigState, error) — 其中之一为 None"""
        cfgs = self.d._find_configs(group_id)
        if not cfgs:
            return None, "该群不在任何配置的执行群中"
        if len(cfgs) == 1:
            return cfgs[0], None
        # 多配置 → 需指定配置名
        cfg_name = parts[start_idx] if len(parts) > start_idx else None
        if cfg_name:
            matched = [c for c in cfgs if c.name == cfg_name]
            if matched:
                return matched[0], None
            return None, f"配置 '{cfg_name}' 不包含此群"
        names = " / ".join(c.name for c in cfgs)
        return None, f"该群属于多个配置，请指定配置名: {names}"

    # ── 开关命令 ──

    async def _cmd_on(self, sender_id: str, group_id: str,
                      parts: List[str]) -> Optional[str]:
        if not await self._is_group_admin(group_id, sender_id):
            return "您不是该群管理员，无法开启验证"

        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        gcfg = self._get_or_create_group_config(cfg.name, group_id)
        if gcfg.enabled:
            return "进群验证已开启"
        gcfg.enabled = True
        self._save_groups(cfg.name)
        return "✅ 已开启进群验证"

    async def _cmd_off(self, sender_id: str, group_id: str,
                       parts: List[str]) -> Optional[str]:
        if not await self._is_group_admin(group_id, sender_id):
            return "您不是该群管理员，无法关闭验证"

        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        gcfg = self._get_or_create_group_config(cfg.name, group_id)
        if not gcfg.enabled:
            return "进群验证未开启"
        gcfg.enabled = False
        self._save_groups(cfg.name)
        return "已关闭进群验证"

    async def _cmd_status(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None

        gcfg = self._get_or_create_group_config(cfg.name, group_id)
        vcfg = self._configs.get(cfg.name, VerifyConfig())

        state = "已开启" if gcfg.enabled else "已关闭"
        lines = [
            f"进群验证: {state}",
            f"配置: {cfg.name}",
            f"总出错次数: {self._fmt_val(vcfg.total_max_errors)}",
            f"重试计入总错误: {'是' if vcfg.include_retry_in_total else '否'}",
            f"非Bot审批超时: {self._fmt_timeout(vcfg.timeout_seconds)}",
            f"Bot审批超时: {self._fmt_timeout(vcfg.bot_approved_timeout)}",
            f"考核块数: {len(vcfg.blocks)}",
        ]
        for i, blk in enumerate(vcfg.blocks, 1):
            q_count = len(blk.questions)
            lines.append(f"  [{i}] {blk.type.value} id={blk.id} 题目数={q_count}")
        return "\n".join(lines)

    # ── 方案设置命令 ──

    async def _cmd_welcome(self, group_id: str,
                           parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 3:
            return "用法: /v welcome <欢迎文本>"
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        vcfg.welcome_text = " ".join(parts[2:])
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"欢迎消息已更新"

    async def _cmd_maxerr(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 3:
            return "用法: /v maxerr <次数 | -1=不限>"
        try:
            val = int(parts[2])
        except ValueError:
            return "请输入整数"
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        vcfg.total_max_errors = val
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"总出错次数已设为: {self._fmt_val(val)}"

    async def _cmd_retry(self, group_id: str) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, [])
        if err:
            return err
        assert cfg is not None
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        vcfg.include_retry_in_total = not vcfg.include_retry_in_total
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        state = "计入" if vcfg.include_retry_in_total else "不计入"
        return f"重试错误{state}总错误次数"

    async def _cmd_timeout(self, group_id: str,
                           parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 3:
            return "用法: /v timeout <秒数 | 0=不限>"
        try:
            val = int(parts[2])
            if val < 0:
                val = 0
        except ValueError:
            return "请输入非负整数（秒）"
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        vcfg.timeout_seconds = val
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"非Bot审批超时已设为: {self._fmt_timeout(val)}"

    async def _cmd_bottimeout(self, group_id: str,
                               parts: List[str]) -> Optional[str]:
        """设置Bot审批成员的验证超时: /v bottimeout <秒数>"""
        cfg, err = self._resolve_single_config(group_id, parts)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 3:
            return "用法: /v bottimeout <秒数 | 0=不限>"
        try:
            val = int(parts[2])
            if val < 0:
                val = 0
        except ValueError:
            return "请输入非负整数（秒）"
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        vcfg.bot_approved_timeout = val
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"Bot审批超时已设为: {self._fmt_timeout(val)}"

    # ── 考核块命令 ──

    async def _cmd_block(self, group_id: str,
                         parts: List[str]) -> Optional[str]:
        if len(parts) < 3:
            return "用法: /v block <add|remove|list|move|edit> [...]"

        sub = parts[2].lower()
        if sub == "add":
            return await self._block_add(group_id, parts)
        elif sub == "remove":
            return await self._block_remove(group_id, parts)
        elif sub == "list":
            return await self._block_list(group_id, parts)
        elif sub == "move":
            return await self._block_move(group_id, parts)
        elif sub == "edit":
            return await self._block_edit(group_id, parts)
        else:
            return f"未知 block 子命令: {sub}"

    async def _block_add(self, group_id: str,
                         parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 4:
            return "用法: /v block add <ALL|RANDOM|SELECT>"

        btype_str = parts[3].upper()
        if btype_str not in ("ALL", "RANDOM", "SELECT"):
            return "考核块类型: ALL / RANDOM / SELECT"

        vcfg = self._configs.get(cfg.name, VerifyConfig())
        blk = Block(
            id=secrets.token_hex(4),
            type=BlockType(btype_str),
        )
        # 全量模式默认 max_errors = 0（一题不错），用户可自行修改
        if btype_str == "ALL":
            blk.max_errors = 0

        vcfg.blocks.append(blk)
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"已添加考核块: {blk.type.value} id={blk.id}"

    async def _block_remove(self, group_id: str,
                            parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 4:
            return "用法: /v block remove <block_id>"

        blk_id = parts[3]
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        old_len = len(vcfg.blocks)
        vcfg.blocks = [b for b in vcfg.blocks if b.id != blk_id]
        if len(vcfg.blocks) == old_len:
            return f"未找到考核块: {blk_id}"

        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"已删除考核块: {blk_id}"

    async def _block_list(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        if not vcfg.blocks:
            return "暂无考核块，使用 /v block add <ALL|RANDOM|SELECT> 添加"

        lines = [f"考核块列表 (配置: {cfg.name}):"]
        for i, blk in enumerate(vcfg.blocks, 1):
            lines.append(
                f"  [{i}] id={blk.id} type={blk.type.value} "
                f"题目数={len(blk.questions)} max_errors={self._fmt_val(blk.max_errors)}"
            )
        return "\n".join(lines)

    async def _block_move(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 5:
            return "用法: /v block move <block_id> <目标位置(从1开始)>"

        blk_id = parts[3]
        try:
            target_pos = int(parts[4]) - 1
        except ValueError:
            return "位置请输入整数（从1开始）"

        vcfg = self._configs.get(cfg.name, VerifyConfig())
        if target_pos < 0 or target_pos >= len(vcfg.blocks):
            return f"位置超出范围 (1-{len(vcfg.blocks)})"

        idx = next((i for i, b in enumerate(vcfg.blocks) if b.id == blk_id), None)
        if idx is None:
            return f"未找到考核块: {blk_id}"

        blk = vcfg.blocks.pop(idx)
        vcfg.blocks.insert(target_pos, blk)
        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"已移动考核块 {blk_id} 到位置 {target_pos + 1}"

    async def _block_edit(self, group_id: str,
                          parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 6:
            return "用法: /v block edit <block_id> <key> <value>\n" \
                   "可选 key: description / max_errors / max_questions / min_correct / required_correct"

        blk_id = parts[3]
        key = parts[4].lower()
        value = " ".join(parts[5:])

        vcfg = self._configs.get(cfg.name, VerifyConfig())
        blk = next((b for b in vcfg.blocks if b.id == blk_id), None)
        if blk is None:
            return f"未找到考核块: {blk_id}"

        valid_keys = {
            "description", "max_errors", "max_questions",
            "min_correct", "required_correct",
        }
        if key not in valid_keys:
            return f"无效 key: {key}，可选: {', '.join(sorted(valid_keys))}"

        try:
            if key == "description":
                blk.description = value
            else:
                val = int(value)
                if key == "max_errors":
                    blk.max_errors = val
                elif key == "max_questions":
                    if blk.type != BlockType.RANDOM:
                        return "max_questions 仅对 RANDOM 块有效"
                    blk.max_questions = val
                elif key == "min_correct":
                    if blk.type != BlockType.RANDOM:
                        return "min_correct 仅对 RANDOM 块有效"
                    blk.min_correct = val
                elif key == "required_correct":
                    if blk.type != BlockType.SELECT:
                        return "required_correct 仅对 SELECT 块有效"
                    blk.required_correct = val
        except ValueError:
            return f"{key} 需要整数"

        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"已更新 block {blk_id}: {key} = {value}"

    # ── 题目命令 ──

    async def _cmd_question(self, group_id: str,
                            parts: List[str]) -> Optional[str]:
        if len(parts) < 3:
            return "用法: /v question <add|remove|list|edit> [...]"

        sub = parts[2].lower()
        if sub == "add":
            return await self._question_add(group_id, parts)
        elif sub == "remove":
            return await self._question_remove(group_id, parts)
        elif sub == "list":
            return await self._question_list(group_id, parts)
        elif sub == "edit":
            return await self._question_edit(group_id, parts)
        else:
            return f"未知 question 子命令: {sub}"

    async def _question_add(self, group_id: str,
                            parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 5:
            return "用法: /v question add <block_id> <calc|qa> [...]"

        blk_id = parts[3]
        qtype = parts[4].lower()

        vcfg = self._configs.get(cfg.name, VerifyConfig())
        blk = next((b for b in vcfg.blocks if b.id == blk_id), None)
        if blk is None:
            return f"未找到考核块: {blk_id}"

        if qtype == "calc":
            return await self._question_add_calc(cfg.name, blk, parts[5:])
        elif qtype == "qa":
            return await self._question_add_qa(cfg.name, blk, parts[5:])
        else:
            return "题目类型: calc (计算题) / qa (问答题)"

    async def _question_add_calc(self, config_name: str, blk: Block,
                                  args: List[str]) -> Optional[str]:
        """添加计算题: /v question add <block_id> calc [addSub] [mulDiv] [square] [numRegex] [stepRegex] [maxAttempts]"""
        q = Question(
            id=secrets.token_hex(4),
            type="calculation",
        )
        # 解析可选参数
        for arg in args:
            arg_lower = arg.lower()
            if arg_lower in ("addsub", "add_sub"):
                q.add_sub = True
            elif arg_lower in ("muldiv", "mul_div"):
                q.mul_div = True
            elif arg_lower == "square":
                q.square = True
            elif arg_lower.startswith("numregex=") or arg_lower.startswith("num_regex="):
                q.num_regex = arg.split("=", 1)[1]
            elif arg_lower.startswith("stepregex=") or arg_lower.startswith("step_regex="):
                q.step_regex = arg.split("=", 1)[1]
            elif arg_lower.startswith("attempts=") or arg_lower.startswith("max_attempts="):
                try:
                    q.max_attempts = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
            else:
                # 尝试作为 maxAttempts 解析
                try:
                    q.max_attempts = int(arg)
                except ValueError:
                    pass

        blk.questions.append(q)
        self._save_config(config_name)
        return f"已添加计算题 id={q.id} 到 block {blk.id}\n" \
               f"  类型: addSub={q.add_sub} mulDiv={q.mul_div} square={q.square}"

    async def _question_add_qa(self, config_name: str, blk: Block,
                                args: List[str]) -> Optional[str]:
        """添加问答题: /v question add <block_id> qa <题目> | <答案正则> [maxAttempts] [listText]"""
        full = " ".join(args)
        parts_q = full.split("|", 2) if "|" in full else full.split("|", 1)
        question_text = parts_q[0].strip() if len(parts_q) > 0 else ""
        rest = parts_q[1].strip() if len(parts_q) > 1 else ""

        # 解析答案正则和可选参数
        rest_parts = rest.split()
        answer_regex = rest_parts[0] if rest_parts else ".*"
        max_attempts = 3
        list_text = ""

        for rp in rest_parts[1:]:
            try:
                max_attempts = int(rp)
            except ValueError:
                list_text = rp

        q = Question(
            id=secrets.token_hex(4),
            type="qa",
            question_text=question_text,
            answer_regex=answer_regex,
            list_text=list_text,
            max_attempts=max_attempts,
        )
        blk.questions.append(q)
        self._save_config(config_name)
        return f"已添加问答题 id={q.id} 到 block {blk.id}"

    async def _question_remove(self, group_id: str,
                               parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 5:
            return "用法: /v question remove <block_id> <question_id>"

        blk_id = parts[3]
        q_id = parts[4]

        vcfg = self._configs.get(cfg.name, VerifyConfig())
        blk = next((b for b in vcfg.blocks if b.id == blk_id), None)
        if blk is None:
            return f"未找到考核块: {blk_id}"

        old_len = len(blk.questions)
        blk.questions = [q for q in blk.questions if q.id != q_id]
        if len(blk.questions) == old_len:
            return f"未找到题目: {q_id}"

        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"已删除题目: {q_id}"

    async def _question_list(self, group_id: str,
                             parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 4:
            return "用法: /v question list <block_id>"

        blk_id = parts[3]
        vcfg = self._configs.get(cfg.name, VerifyConfig())
        blk = next((b for b in vcfg.blocks if b.id == blk_id), None)
        if blk is None:
            return f"未找到考核块: {blk_id}"

        if not blk.questions:
            return f"block {blk_id} 暂无题目"

        lines = [f"题目列表 (block={blk_id}):"]
        for i, q in enumerate(blk.questions, 1):
            if q.type == "calculation":
                desc = f"计算题 addSub={q.add_sub} mulDiv={q.mul_div} square={q.square}"
            else:
                desc = f"问答题: {q.question_text[:30]}"
            lines.append(
                f"  [{i}] id={q.id} type={q.type} attempts={self._fmt_val(q.max_attempts)} {desc}"
            )
        return "\n".join(lines)

    async def _question_edit(self, group_id: str,
                             parts: List[str]) -> Optional[str]:
        cfg, err = self._resolve_single_config(group_id, parts, start_idx=3)
        if err:
            return err
        assert cfg is not None
        if len(parts) < 7:
            return "用法: /v question edit <block_id> <question_id> <key> <value>"

        blk_id = parts[3]
        q_id = parts[4]
        key = parts[5].lower()
        value = " ".join(parts[6:])

        vcfg = self._configs.get(cfg.name, VerifyConfig())
        blk = next((b for b in vcfg.blocks if b.id == blk_id), None)
        if blk is None:
            return f"未找到考核块: {blk_id}"
        q = next((q for q in blk.questions if q.id == q_id), None)
        if q is None:
            return f"未找到题目: {q_id}"

        valid_keys = {
            "max_attempts", "add_sub", "mul_div", "square",
            "num_regex", "step_regex", "square_num_regex",
            "question_text", "answer_regex", "list_text",
        }
        if key not in valid_keys:
            return f"无效 key: {key}，可选: {', '.join(sorted(valid_keys))}"

        try:
            if key in ("max_attempts",):
                setattr(q, key, int(value))
            elif key in ("add_sub", "mul_div", "square"):
                setattr(q, key, value.lower() in ("true", "1", "yes"))
            else:
                setattr(q, key, value)
        except (ValueError, TypeError):
            return f"{key} 格式不正确"

        self._configs[cfg.name] = vcfg
        self._save_config(cfg.name)
        return f"已更新题目 {q_id}: {key}"

    # ════════════════════════════════════════════════════════════
    # 事件处理 — 成员入群
    # ════════════════════════════════════════════════════════════

    async def _get_self_id(self) -> Optional[int]:
        """获取机器人自身 QQ（缓存）"""
        if self._self_id is not None:
            return self._self_id
        try:
            info = await self.d._api.get_login_info()
            if info and "user_id" in info:
                self._self_id = int(info["user_id"])
                return self._self_id
        except Exception:
            logger.exception("获取机器人自身 QQ 失败")
        return None

    async def on_member_increase(self, event: dict):
        """成员入群通知 → 启动验证"""
        if event.get("notice_type") != "group_increase":
            return

        group_id = event.get("group_id", 0)
        user_id = event.get("user_id", 0)

        if not group_id or not user_id:
            return

        # 机器人自身入群不验证
        self_id = await self._get_self_id()
        if self_id and int(user_id) == self_id:
            return

        gid_str = str(group_id)

        # 检查验证是否启用
        cfgs = self.d._find_configs(gid_str)
        enabled = False
        config_name = None
        for c in cfgs:
            gcfg = self._groups.get(c.name, {}).get(gid_str)
            if gcfg and gcfg.enabled:
                enabled = True
                config_name = c.name
                break

        if not enabled or not config_name:
            return

        # 获取验证方案
        vcfg = self._configs.get(config_name)
        if not vcfg or not vcfg.blocks:
            logger.warning(f"群 {group_id} 验证已启用但未配置考核块")
            return

        await self._start_session(int(group_id), int(user_id),
                                   config_name, vcfg)

    async def _start_session(self, group_id: int, user_id: int,
                              config_name: str, vcfg: VerifyConfig):
        """创建验证会话并开始"""
        # 构建 BlockSession 列表
        block_sessions = []
        for blk in vcfg.blocks:
            instances = self._build_question_instances(blk)
            bs = BlockSession(block=blk, question_instances=instances)

            if blk.type == BlockType.SELECT:
                bs.remaining_questions = list(instances)
                bs.awaiting_selection = True
            elif blk.type == BlockType.RANDOM:
                # 随机抽取不重复题目（已在 _build_question_instances 中打乱）
                pass

            block_sessions.append(bs)

        bot_approved = self.ap.is_bot_approved(group_id, user_id)

        session = VerifySession(
            group_id=group_id,
            user_id=user_id,
            config_name=config_name,
            verify_config=vcfg,
            block_sessions=block_sessions,
            bot_approved=bot_approved,
        )

        # 超时任务 — 根据入群来源选用不同的超时
        timeout = vcfg.bot_approved_timeout if bot_approved else vcfg.timeout_seconds
        if timeout > 0:
            session.timeout_task = asyncio.create_task(
                self._timeout_handler(group_id, user_id, timeout)
            )

        self.sessions[(group_id, user_id)] = session

        # 构建欢迎消息（文本+AT+超时提示+答题说明图，合并为一条消息）
        await self._send_welcome(group_id, user_id, vcfg, timeout)

        # 开始第一个考核块
        await self._send_current_block(session)

    async def _send_welcome(self, group_id: int, user_id: int,
                             vcfg: VerifyConfig, timeout: int):
        """发送欢迎消息：AT + 欢迎文本 + 超时提示 + 答题说明图，合并一条消息"""
        import base64

        msg_segments: list[dict] = []

        # 1. 构建欢迎文本消息段（逐段处理 {@新成员} 占位符）
        welcome = vcfg.welcome_text
        total_label = "不限" if vcfg.total_max_errors == -1 else str(vcfg.total_max_errors)

        # 按 {@新成员} 分割文本，在 AT 段穿插普通文本段
        parts = welcome.split("{@新成员}")
        for i, part in enumerate(parts):
            if i > 0:
                msg_segments.append({
                    "type": "at",
                    "data": {"qq": str(user_id)},
                })
            # 替换其他占位符
            part = part.replace("{总最多出错数}", total_label)
            if part:
                msg_segments.append({
                    "type": "text",
                    "data": {"text": part},
                })

        # 2. 超时提示
        if timeout > 0:
            msg_segments.append({
                "type": "text",
                "data": {"text": f"\n请在 {timeout} 秒内完成验证"},
            })

        # 3. 答题说明图
        png = self.d._render_png(render_verify_guide)
        if png:
            msg_segments.append({
                "type": "image",
                "data": {"file": f"base64://{base64.b64encode(png).decode()}"},
            })

        await self.d.send_message(group_id, msg_segments)

    async def _timeout_handler(self, group_id: int, user_id: int,
                                timeout_sec: int):
        """超时处理：到期未完成验证则踢出"""
        await asyncio.sleep(timeout_sec)
        key = (group_id, user_id)
        session = self.sessions.get(key)
        if session and session.status == "active":
            reason = f"验证超时（{timeout_sec}秒内未完成验证）"
            await self._fail_session(session, reason)

    # ════════════════════════════════════════════════════════════
    # 事件处理 — 答题拦截
    # ════════════════════════════════════════════════════════════

    async def on_raw_message(self, event: dict):
        """拦截验证中的用户消息"""
        if event.get("message_type") != "group":
            return

        group_id = event.get("group_id", 0)
        user_id = event.get("user_id", 0)
        raw = event.get("raw_message", event.get("message", "")).strip()

        key = (int(group_id), int(user_id))
        session = self.sessions.get(key)
        if not session or session.status != "active":
            return

        # 拦截消息，不再传播
        await self._handle_answer(session, raw)

    async def _handle_answer(self, session: VerifySession, raw: str):
        """处理验证回答"""
        bs = session.block_sessions[session.current_block_idx]
        blk = bs.block
        vcfg = session.verify_config

        if blk.type == BlockType.SELECT and bs.awaiting_selection:
            # 用户在选择题目序号
            await self._handle_selection(session, bs, raw)
            return

        # 确定当前题目实例
        if blk.type == BlockType.SELECT:
            qi = bs.current_selected
            if qi is None:
                return
        else:
            # ALL / RANDOM: 按序号取题
            if bs.current_q_idx >= len(bs.question_instances):
                return
            qi = bs.question_instances[bs.current_q_idx]

        q = qi.question

        # 判断对错
        correct = self._check_answer(raw, qi)

        if correct:
            qi.attempts += 1
            bs.correct_count += 1
            await self.d.send_message(session.group_id, "✅ 正确")

            if blk.type == BlockType.SELECT:
                # 自选模式：从可选列表移除已答对的题，回到选择界面
                bs.remaining_questions = [
                    x for x in bs.remaining_questions
                    if x.question.id != q.id
                ]
                bs.current_selected = None
                bs.awaiting_selection = True
                # 检查是否完成
                if bs.correct_count >= blk.required_correct:
                    bs.passed = True
                    bs.finished = True
            else:
                # ALL / RANDOM：下一题
                bs.current_q_idx += 1
                if blk.type == BlockType.RANDOM:
                    if bs.correct_count >= blk.min_correct:
                        bs.passed = True
                        bs.finished = True

            # 检查块结束
            if not bs.finished and blk.type == BlockType.ALL:
                if bs.current_q_idx >= len(bs.question_instances):
                    bs.passed = (bs.error_count <= blk.max_errors)
                    bs.finished = True
            elif not bs.finished and blk.type == BlockType.RANDOM:
                if bs.current_q_idx >= len(bs.question_instances):
                    # 题目耗尽
                    if bs.correct_count >= blk.min_correct:
                        bs.passed = True
                    bs.finished = True

        else:
            # 错误
            qi.attempts += 1
            if vcfg.include_retry_in_total:
                session.total_errors += 1

            # 检查是否有重试次数（max_attempts=0 → 共1次机会，max_attempts=1 → 共2次，以此类推）
            if q.max_attempts == -1 or qi.attempts <= q.max_attempts:
                remaining = ""
                if q.max_attempts != -1:
                    remaining = f"（剩余 {q.max_attempts + 1 - qi.attempts} 次）"
                await self.d.send_message(
                    session.group_id, f"❌ 错误，请重试{remaining}",
                )
                return  # 等待重试
            else:
                # 最终失败
                qi.final_failed = True
                if not vcfg.include_retry_in_total:
                    session.total_errors += 1
                bs.error_count += 1

                await self.d.send_message(
                    session.group_id,
                    f"❌ 错误，本题最终未通过（已达最大尝试次数）",
                )

                # 检查块失败 / 总错误超限
                if await self._check_failure(session, bs):
                    return

                if blk.type == BlockType.SELECT:
                    # 从可选列表中移除失败题目
                    bs.remaining_questions = [
                        x for x in bs.remaining_questions
                        if x.question.id != q.id
                    ]
                    bs.current_selected = None
                    bs.awaiting_selection = True
                    # 检查是否可选题目耗尽
                    if not bs.remaining_questions:
                        bs.finished = True
                        # 未达 required_correct → 失败
                else:
                    bs.current_q_idx += 1
                    if blk.type == BlockType.ALL:
                        # 全量模式：若错误数已超限则提前结束，否则全部发完后判定
                        if blk.max_errors != -1 and bs.error_count > blk.max_errors:
                            bs.finished = True
                            bs.passed = False
                        elif bs.current_q_idx >= len(bs.question_instances):
                            bs.finished = True
                            bs.passed = (bs.error_count <= blk.max_errors)
                    elif blk.type == BlockType.RANDOM:
                        if bs.current_q_idx >= len(bs.question_instances):
                            bs.finished = True

        # 检查是否整体失败
        if await self._check_failure(session, bs):
            return

        # 块结束检查
        if bs.finished:
            if bs.passed:
                # 进入下一块
                session.current_block_idx += 1
                if session.current_block_idx >= len(session.block_sessions):
                    await self._pass_session(session)
                else:
                    await self._send_current_block(session)
            else:
                # 块失败
                await self._fail_session(
                    session,
                    f"验证失败：考核块 [{blk.id}] 未通过",
                )
        else:
            # 继续发下一题
            if blk.type == BlockType.SELECT:
                await self._send_selection_list(session, bs)
            else:
                await self._send_next_question(session, bs)

    async def _handle_selection(self, session: VerifySession,
                                 bs: BlockSession, raw: str):
        """处理 SELECT 模式题号选择"""
        try:
            idx = int(raw.strip()) - 1
        except ValueError:
            await self.d.send_message(
                session.group_id,
                "请输入可选题目序号（数字）",
            )
            return

        if idx < 0 or idx >= len(bs.remaining_questions):
            await self.d.send_message(
                session.group_id,
                f"无效序号，可选范围: 1-{len(bs.remaining_questions)}",
            )
            return

        qi = bs.remaining_questions[idx]
        bs.awaiting_selection = False
        bs.current_selected = qi  # 记录当前选中的题目
        q = qi.question
        if q.type == "calculation":
            expr = qi.generated_expression
        else:
            expr = self._replace_question_placeholders(
                q.question_text, q.max_attempts,
            )

        png = self.d._render_png(
            lambda: render_question_card(
                expression=expr,
                attempts=qi.attempts,
                max_attempts=q.max_attempts,
                progress=f"自选题目 {idx + 1}",
            )
        )
        if png:
            await self.d.send_image(session.group_id, png)
        else:
            total_attempts = "不限" if q.max_attempts == -1 else str(q.max_attempts + 1)
            await self.d.send_message(
                session.group_id,
                f"[自选题目 {idx + 1}] {expr}\n(尝试: {qi.attempts}/{total_attempts})",
            )

    async def _send_selection_list(self, session: VerifySession,
                                    bs: BlockSession):
        """发送 SELECT 模式可选题目列表"""
        if not bs.remaining_questions:
            return

        lines = ["请选择题目（回复序号）:"]
        for i, qi in enumerate(bs.remaining_questions, 1):
            q = qi.question
            if q.list_text:
                text = self._replace_question_placeholders(
                    q.list_text, q.max_attempts,
                )
            elif q.type == "qa":
                text = q.question_text[:30]
            else:
                text = f"计算题 (id={q.id})"
            lines.append(f"  [{i}] {text}")

        await self.d.send_message(session.group_id, "\n".join(lines))

    async def _check_failure(self, session: VerifySession,
                              bs: BlockSession) -> bool:
        """检查是否满足失败条件，返回 True 表示已失败"""
        vcfg = session.verify_config
        blk = bs.block

        # 总错误超限
        if vcfg.total_max_errors != -1 and \
           session.total_errors >= vcfg.total_max_errors:
            await self._fail_session(
                session,
                f"验证失败：超出总错误次数 "
                f"({session.total_errors}/{vcfg.total_max_errors})",
            )
            return True

        # 块错误超限
        if blk.max_errors != -1 and bs.error_count > blk.max_errors:
            bs.finished = True
            bs.passed = False
            await self._fail_session(
                session,
                f"验证失败：考核块 [{blk.id}] 错误数超限 "
                f"({bs.error_count}/{blk.max_errors})",
            )
            return True

        return False

    # ════════════════════════════════════════════════════════════
    # 题目发送
    # ════════════════════════════════════════════════════════════

    async def _send_current_block(self, session: VerifySession):
        """开始当前考核块"""
        bs = session.block_sessions[session.current_block_idx]
        blk = bs.block

        # 发送块描述
        if blk.description:
            desc = self._replace_block_placeholders(
                blk.description, blk,
            )
            await self.d.send_message(session.group_id, desc)

        if blk.type == BlockType.SELECT:
            await self._send_selection_list(session, bs)
        else:
            await self._send_next_question(session, bs)

    async def _send_next_question(self, session: VerifySession,
                                   bs: BlockSession):
        """发送当前题目（渲染为图片）"""
        if bs.current_q_idx >= len(bs.question_instances):
            return

        qi = bs.question_instances[bs.current_q_idx]
        q = qi.question
        blk = bs.block

        # 题目文本
        if q.type == "calculation":
            expr = qi.generated_expression
        else:
            expr = self._replace_question_placeholders(
                q.question_text, q.max_attempts,
            )

        # 进度信息
        if blk.type == BlockType.RANDOM:
            progress = (
                f"题目 {bs.current_q_idx + 1}/{len(bs.question_instances)}"
                f"  |  需答对: {blk.min_correct}  |  已答对: {bs.correct_count}"
            )
        elif blk.type == BlockType.ALL:
            progress = f"题目 {bs.current_q_idx + 1}/{len(bs.question_instances)}"
        else:
            progress = ""

        png = self.d._render_png(
            lambda: render_question_card(
                expression=expr,
                attempts=qi.attempts,
                max_attempts=q.max_attempts,
                progress=progress,
            )
        )
        if png:
            await self.d.send_image(session.group_id, png)
        else:
            # 回退纯文本
            total_attempts = "不限" if q.max_attempts == -1 else str(q.max_attempts + 1)
            await self.d.send_message(
                session.group_id,
                f"{progress}{expr}\n(尝试: {qi.attempts}/{total_attempts})",
            )

    # ════════════════════════════════════════════════════════════
    # 答案判断
    # ════════════════════════════════════════════════════════════

    def _check_answer(self, raw: str, qi: QuestionInstance) -> bool:
        """判断用户答案是否正确"""
        q = qi.question
        answer = raw.strip()[: _MAX_ANSWER_LEN]

        if q.type == "calculation":
            # 数值比较（容忍浮点误差）
            expected = qi.generated_answer
            try:
                user_val = float(answer)
                exp_val = float(expected)
                return abs(user_val - exp_val) < 0.01
            except (ValueError, TypeError):
                # 非数值：检查是否包含预期结果
                return expected.lower() in answer.lower()
        else:
            # 问答题：正则匹配
            try:
                return bool(re.search(q.answer_regex, answer))
            except re.error:
                # 正则无效时做简单包含匹配
                return q.answer_regex.lower() in answer.lower()

    # ════════════════════════════════════════════════════════════
    # 会话结束
    # ════════════════════════════════════════════════════════════

    async def _pass_session(self, session: VerifySession):
        """验证通过"""
        session.status = "passed"
        self._cancel_timeout(session)
        self.sessions.pop((session.group_id, session.user_id), None)

        await self.d.send_message(session.group_id, "🎉 验证通过")
        logger.info(
            f"验证通过: group={session.group_id} user={session.user_id}"
        )

    async def _fail_session(self, session: VerifySession, reason: str):
        """验证失败 → 踢出"""
        if session.status != "active":
            return  # 已被 _pass_session 或另一个 _fail_session 处理
        session.status = "failed"
        # 先从 sessions 移除，防止超时任务在此期间重复触发
        self.sessions.pop((session.group_id, session.user_id), None)

        await self.d.send_message(session.group_id, reason)
        await asyncio.sleep(1.5)

        try:
            await self.d.kick(session.group_id, session.user_id,
                             reject_add=False)
            logger.info(
                f"验证失败已踢出: group={session.group_id} "
                f"user={session.user_id} reason={reason}"
            )
        except Exception:
            logger.exception("踢出成员失败")
        finally:
            # 取消超时任务必须放在最后，否则超时任务调用本函数时会取消自身
            # → 在下一个 await 处抛出 CancelledError → kick 被跳过
            self._cancel_timeout(session)

    def _cancel_timeout(self, session: VerifySession):
        """取消超时任务（安全：不会取消当前正在执行的任务）"""
        if session.timeout_task and not session.timeout_task.done():
            current = asyncio.current_task()
            if session.timeout_task is not current:
                session.timeout_task.cancel()

    # ════════════════════════════════════════════════════════════
    # 题目构建
    # ════════════════════════════════════════════════════════════

    def _build_question_instances(self, blk: Block) -> List[QuestionInstance]:
        """为考核块生成题目实例（含计算题答案预生成）"""
        instances = []
        for q in blk.questions:
            qi = QuestionInstance(question=q)
            if q.type == "calculation":
                expr, ans = self._generate_calc(q)
                qi.generated_expression = expr
                qi.generated_answer = ans
            instances.append(qi)

        if blk.type == BlockType.RANDOM:
            # 随机打乱
            random.shuffle(instances)
            # 限制数量
            if blk.max_questions != -1 and blk.max_questions < len(instances):
                instances = instances[: blk.max_questions]

        return instances

    # ════════════════════════════════════════════════════════════
    # 计算题生成
    # ════════════════════════════════════════════════════════════

    def _generate_calc(self, q: Question) -> tuple:
        """生成计算题算式和答案。返回 (expression, answer)。"""
        # 从正则推导步数
        step_count = self._random_from_regex(q.step_regex, 1, 3)

        # 收集可用二元运算符（square 单独处理）
        bin_ops = []
        if q.add_sub:
            bin_ops.extend(["+", "-"])
        if q.mul_div:
            bin_ops.extend(["*", "/"])

        if not bin_ops and not q.square:
            return "1 + 1 = ?", "2"

        # 生成初始数字，分开展示值和运算值（平方仅影响运算值）
        display_first = self._random_from_regex(q.num_regex, 1, 100)
        value_first = display_first * display_first if q.square else display_first
        remaining = max(step_count - 1, 0) if q.square else step_count
        ops: list[tuple[str, int]] = []  # [(op, num), ...]

        for _ in range(remaining):
            if not bin_ops:
                break
            op = random.choice(bin_ops)
            num = self._random_from_regex(q.num_regex, 1, 100)
            if op == "/" and num == 0:
                num = 1
            ops.append((op, num))

        # ── 构建表达式（标准数学写法，不需括号） ──
        expr = str(display_first)
        if q.square:
            expr += "^2"
        for op, num in ops:
            expr += f" {op} {num}"
        expression = expr + " = ?"

        # ── 求值：和括号一致的优先级（先 */ 后 +-，同优先级左到右） ──
        # 用 tokens 列表求值
        tokens: list = [value_first]
        for op, num in ops:
            tokens.append(op)
            tokens.append(num)

        # 第一遍：处理所有 */
        ti = 1
        while ti < len(tokens):
            if tokens[ti] in ("*", "/"):
                left = tokens[ti - 1]
                right = tokens[ti + 1]
                tokens[ti - 1] = left * right if tokens[ti] == "*" else (left // right if right != 0 else left)
                tokens.pop(ti)
                tokens.pop(ti)
            else:
                ti += 2

        # 第二遍：处理所有 +-
        ti = 1
        while ti < len(tokens):
            if tokens[ti] in ("+", "-"):
                left = tokens[ti - 1]
                right = tokens[ti + 1]
                tokens[ti - 1] = left + right if tokens[ti] == "+" else left - right
                tokens.pop(ti)
                tokens.pop(ti)
            else:
                ti += 2

        return expression, str(tokens[0])

    def _random_from_regex(self, regex: str, min_val: int,
                            max_val: int) -> int:
        """从正则表达式推导随机数。如 [1-9]\\d{0,2} → 1-3位数字。"""
        if not regex:
            return random.randint(min_val, max_val)
        try:
            bs = "\\"  # 反斜杠，用于构建匹配 literal \d 的正则

            # 解析 [low-high]
            m = re.search(r'\[(\d+)-(\d+)\]', regex)
            first_lo = int(m.group(1)) if m else 1
            first_hi = int(m.group(2)) if m else 9

            # 解析 \\d{N} 或 \\d{N,M}，如 \\d{2} → tail_min=2,tail_max=2
            p = bs + bs + "d" + bs + "{(" + bs + "d+)(?:,(" + bs + "d+))?" + bs + "}"
            repeat_m = re.search(p, regex)
            if repeat_m:
                tail_min = int(repeat_m.group(1))
                tail_max = int(repeat_m.group(2)) if repeat_m.group(2) else tail_min
            else:
                tail_min = tail_max = 0

            # [1-9] 在 \\d 前面 ⇒ 额外加一位
            p2 = r'\[(\d+)-(\d+)\]' + bs + bs + "d"
            has_leading = bool(re.match(p2, regex))
            leading_digits = 1 if has_leading else 0

            # 若既无 leading 也无 \\d{...}，则为纯 [1-9] 单数字
            if not has_leading and tail_max == 0:
                tail_min = tail_max = 1

            total_min = leading_digits + tail_min
            total_max = leading_digits + tail_max
            total_min = max(total_min, 1)  # 至少 1 位
            digits = random.randint(total_min, total_max)

            if digits == 1:
                return random.randint(max(first_lo, min_val), min(first_hi, max_val))

            # 多位：首位在 [first_lo, first_hi]，其余位在 [0, 9]
            first = random.randint(first_lo, first_hi)
            rest_lo = 10 ** (digits - 1)
            rest = random.randint(0, rest_lo - 1) if rest_lo > 1 else 0
            return first * rest_lo + rest
        except Exception:
            return random.randint(min_val, max_val)

    # ════════════════════════════════════════════════════════════
    # 占位符替换
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _replace_block_placeholders(text: str, blk: Block) -> str:
        """替换块描述占位符"""
        q_count = len(blk.questions)
        text = text.replace("{题库总数}", str(q_count))

        if blk.type == BlockType.ALL:
            text = text.replace("{总题目数}", str(q_count))
        elif blk.type == BlockType.RANDOM:
            actual = blk.max_questions if blk.max_questions != -1 else q_count
            text = text.replace(
                "{随机出题数}",
                f"不限制({q_count})" if blk.max_questions == -1 else str(actual),
            )
            text = text.replace("{最少答对数}", str(blk.min_correct))
        elif blk.type == BlockType.SELECT:
            text = text.replace("{总题目数}", str(q_count))
            text = text.replace("{需答对数量}", str(blk.required_correct))

        text = text.replace(
            "{最多出错数}",
            "不限制" if blk.max_errors == -1 else str(blk.max_errors),
        )

        return text

    @staticmethod
    def _replace_question_placeholders(text: str,
                                        max_attempts: int) -> str:
        """替换题目占位符"""
        return text.replace(
            "{每题尝试次数}",
            "不限" if max_attempts == -1 else str(max_attempts),
        )

    # ════════════════════════════════════════════════════════════
    # 工具
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _fmt_val(val: int) -> str:
        """格式化数值（-1 → 不限）"""
        return "不限" if val == -1 else str(val)

    @staticmethod
    def _fmt_timeout(seconds: int) -> str:
        """格式化超时"""
        return "不限" if seconds == 0 else f"{seconds}秒"
