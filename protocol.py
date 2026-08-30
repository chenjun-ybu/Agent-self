"""
Protocol: 结构化工具调用协议

定义工具调用请求与响应的统一格式，将工具名称、输入参数、执行状态、
返回结果、错误信息和用户确认请求纳入规范化结构。

Tool  提供具体操作能力（如 SMILES 校验）
Skill 组织完成一类任务的方法（如化学数据处理流程）
Protocol 规定能力如何被发现、调用、传递结果并接受约束
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
import json
import uuid


class CallStatus(str, Enum):
    """工具调用状态"""
    SUCCESS = "success"
    ERROR = "error"
    NEEDS_CONFIRMATION = "needs_confirmation"
    SKIPPED = "skipped"


@dataclass
class ToolCallRequest:
    """结构化工具调用请求"""
    tool_name: str
    parameters: dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: "")

    def to_dict(self) -> dict:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class ToolCallResponse:
    """结构化工具调用响应"""
    tool_name: str
    call_id: str
    status: CallStatus
    result: Any = None
    error: Optional[str] = None
    confirmation_request: Optional[dict] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "status": self.status.value,
            "result": self.result,
        }
        if self.error:
            d["error"] = self.error
        if self.confirmation_request:
            d["confirmation_request"] = self.confirmation_request
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class ExecutionRecord:
    """单步执行记录，构成 Skill 的执行轨迹"""
    step: int
    step_name: str
    request: ToolCallRequest
    response: ToolCallResponse

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "step_name": self.step_name,
            "request": self.request.to_dict(),
            "response": self.response.to_dict(),
        }


@dataclass
class SkillResult:
    """Skill 执行的最终结果"""
    skill_name: str
    status: CallStatus
    cleaned_data: list[dict] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    execution_records: list[ExecutionRecord] = field(default_factory=list)
    final_message: str = ""
    confirmation_request: Optional[dict] = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "skill_name": self.skill_name,
            "status": self.status.value,
            "cleaned_data": self.cleaned_data,
            "issues": self.issues,
            "execution_records": [r.to_dict() for r in self.execution_records],
            "final_message": self.final_message,
        }
        if self.confirmation_request:
            d["confirmation_request"] = self.confirmation_request
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
