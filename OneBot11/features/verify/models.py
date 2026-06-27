"""
数据模型 — Pydantic BaseModel + dataclass
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field


def _to_camel(name: str) -> str:
    """snake_case → camelCase"""
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


# ════════════════════════════════════════════════════════════════
# 加群审批
# ════════════════════════════════════════════════════════════════

class ApprovalConfig(BaseModel):
    """加群审批方案定义（每配置一份）"""
    comment_regex: str = ""                 # 入群申请 comment 正则，空=不校验直接同意
    reject_reason: str = "入群验证信息不匹配，请重新申请并填写正确的验证信息"
    on_mismatch: str = "ignore"             # 不匹配时的行为: "reject"=拒绝, "ignore"=忽略(交管理员)
    welcome_text: str = ""                  # 审批通过后入群欢迎文本，空=不发送。支持 {@新成员}

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


class ApprovalGroupConfig(BaseModel):
    """单群加群审批开关"""
    enabled: bool = False

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


# ════════════════════════════════════════════════════════════════
# 进群验证 — 方案定义
# ════════════════════════════════════════════════════════════════

class BlockType(str, Enum):
    ALL = "ALL"
    RANDOM = "RANDOM"
    SELECT = "SELECT"


class Question(BaseModel):
    """题目定义 — 统一模型，按 type 区分计算题/问答题"""
    id: str
    type: str = "qa"                        # "calculation" | "qa"
    max_attempts: int = 3                   # -1=无限, 0=一次错即失败

    # 计算题字段
    add_sub: bool = True
    mul_div: bool = False
    square: bool = False
    num_regex: str = r"[1-9]\d{0,2}"        # 数字范围正则
    step_regex: str = r"[1-3]"              # 运算符数量正则
    square_num_regex: str = ""              # 平方底数专用正则，空则用 numRegex

    # 问答题字段
    question_text: str = ""
    answer_regex: str = ""
    list_text: str = ""                     # 自选块列表显示文本

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


class Block(BaseModel):
    """考核块定义"""
    id: str
    type: BlockType = BlockType.ALL
    description: str = ""                   # 块描述，支持占位符
    max_errors: int = -1                    # 本块最多允许错误数，-1=不限

    # RANDOM 专属
    max_questions: int = -1                 # 最多出题数，-1=不限（全部）
    min_correct: int = 1                    # 最少答对题数

    # SELECT 专属
    required_correct: int = 1               # 需自选答对数量

    questions: List[Question] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


class VerifyConfig(BaseModel):
    """进群验证方案定义（每配置一份，无预设概念）"""
    welcome_text: str = "欢迎{@新成员}加入本群！请完成以下验证，共有{总最多出错数}次容错机会。"
    total_max_errors: int = 5               # 总最多出错次数，-1=不限制
    include_retry_in_total: bool = True     # 重试错误是否计入总错误
    timeout_seconds: int = 0                # 非Bot审批成员的验证超时（秒），0=不限制
    bot_approved_timeout: int = 0           # Bot审批成员的验证超时（秒），0=不限制
    blocks: List[Block] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


class VerifyGroupConfig(BaseModel):
    """单群进群验证开关"""
    enabled: bool = False

    model_config = {"populate_by_name": True, "alias_generator": _to_camel}


# ════════════════════════════════════════════════════════════════
# 运行时（不持久化）
# ════════════════════════════════════════════════════════════════

@dataclass
class QuestionInstance:
    """题目实例 — 运行时包含预生成的计算题答案"""
    question: Question
    generated_expression: str = ""          # 计算题生成的算式文本
    generated_answer: str = ""              # 计算题预生成的正确答案
    attempts: int = 0                       # 当前已尝试次数
    final_failed: bool = False              # 是否已最终失败


@dataclass
class BlockSession:
    """考核块运行时状态"""
    block: Block
    question_instances: List[QuestionInstance] = field(default_factory=list)
    current_q_idx: int = 0                  # 当前题目序号（ALL/RANDOM）
    correct_count: int = 0                  # 本块已答对数
    error_count: int = 0                    # 本块最终错误数
    finished: bool = False                  # 块是否已结束
    passed: bool = False                    # 块是否通过
    # SELECT 模式专属
    remaining_questions: List[QuestionInstance] = field(default_factory=list)
    current_selected: Optional[QuestionInstance] = None  # 当前选中的题目
    awaiting_selection: bool = False        # 等待用户选择题号


@dataclass
class VerifySession:
    """验证会话 — 运行时状态"""
    group_id: int
    user_id: int
    config_name: str
    verify_config: VerifyConfig
    block_sessions: List[BlockSession] = field(default_factory=list)
    current_block_idx: int = 0
    total_errors: int = 0
    status: str = "active"                  # active | passed | failed
    timeout_task: Optional[object] = None   # asyncio.Task | None
    bot_approved: bool = False              # 是否由 Bot 审批入群
