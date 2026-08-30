"""
SkillExecutor: Skill 执行器

加载 Skill 的 YAML 描述，按其中定义的 execution_steps 编排工具调用，
将多步骤流程转化为可复用、可约束的执行方法。

这是 Skill 外部化的核心——程序性知识不再是 LLM 临时生成的，
而是被固化为可加载、可重复执行的结构化流程。
"""

from protocol import (
    ToolCallRequest, ToolCallResponse, CallStatus,
    ExecutionRecord, SkillResult,
)
from tool_registry import ToolRegistry, create_default_registry
from dataclasses import dataclass, field
from typing import Any, Optional
import os

try:
    import yaml
except ImportError:
    yaml = None
    import json


class ChemicalDataProcessingSkill:
    """
    化学数据处理 Skill 的执行器。
    按照 YAML 中定义的三步流程编排工具：
    1. SMILES 校验 → 2. 单位转换 → 3. 重复检查
    """

    SKILL_NAME = "chemical_data_processing"
    SKILL_FILE = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "skills", "chemical_data_processing.yaml"
    )

    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.skill_spec = self._load_skill_spec()

    def _load_skill_spec(self) -> dict:
        """加载 Skill YAML 描述文件"""
        if os.path.exists(self.SKILL_FILE):
            with open(self.SKILL_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            if yaml:
                return yaml.safe_load(content)
            else:
                # 简单回退：不解析 YAML，使用硬编码
                pass

        # 回退到硬编码的 Skill 规格
        return {
            "name": self.SKILL_NAME,
            "description": "化学数据处理 Skill",
            "execution_steps": [
                {"step": 1, "name": "validate_smiles", "tool": "smiles_validator"},
                {"step": 2, "name": "convert_units", "tool": "unit_converter"},
                {"step": 3, "name": "check_duplicates", "tool": "duplicate_checker"},
            ],
        }

    def get_skill_info(self) -> dict:
        """返回 Skill 的描述信息"""
        return {
            "name": self.skill_spec.get("name", self.SKILL_NAME),
            "description": self.skill_spec.get("description", ""),
            "applicable_scenarios": self.skill_spec.get("applicable_scenarios", []),
            "required_tools": self.skill_spec.get("required_tools", []),
            "execution_steps": [
                {"step": s["step"], "name": s["name"], "tool": s["tool"]}
                for s in self.skill_spec.get("execution_steps", [])
            ],
        }

    def execute(
        self,
        records: list[dict],
        target_unit: str = "",
        property_type: str = "",
        user_decision: Optional[str] = None,
    ) -> SkillResult:
        """
        执行化学数据处理 Skill。

        Args:
            records:       化学数据记录列表
            target_unit:   目标换算单位
            property_type: 性质类型 (temperature/pressure/concentration)
            user_decision: 当上一次执行需要确认时，用户给出的决策
                          (keep_first/keep_last/keep_both/manual_review)

        Returns:
            SkillResult: 包含清洗数据、问题列表和执行记录
        """
        result = SkillResult(skill_name=self.SKILL_NAME, status=CallStatus.SUCCESS)
        current_data = list(records)
        step_num = 0

        # ─── Step 1: SMILES 校验 ───
        step_num += 1
        req1 = ToolCallRequest(
            tool_name="smiles_validator",
            parameters={
                "records": current_data,
                "required_fields": ["sample_id", "SMILES", "property_value", "unit"],
            },
        )
        resp1 = self.registry.call(req1)
        result.execution_records.append(
            ExecutionRecord(step=step_num, step_name="validate_smiles", request=req1, response=resp1)
        )

        if resp1.status == CallStatus.ERROR and not resp1.result.get("valid_records"):
            # 所有记录无效，终止
            result.status = CallStatus.ERROR
            result.issues = resp1.result.get("issues", ["所有 SMILES 校验失败"])
            result.final_message = "流程终止：所有记录的 SMILES 校验均失败"
            return result

        # 收集有效记录和问题
        valid_records = resp1.result.get("valid_records", [])
        result.issues.extend(resp1.result.get("issues", []))
        current_data = valid_records

        # ─── Step 2: 单位转换 ───
        step_num += 1
        req2 = ToolCallRequest(
            tool_name="unit_converter",
            parameters={
                "records": current_data,
                "target_unit": target_unit,
                "property_type": property_type,
            },
        )
        resp2 = self.registry.call(req2)
        result.execution_records.append(
            ExecutionRecord(step=step_num, step_name="convert_units", request=req2, response=resp2)
        )

        if resp2.status == CallStatus.ERROR:
            result.issues.extend(resp2.result.get("issues", ["单位转换失败"]))
            result.status = CallStatus.ERROR
            result.final_message = "单位转换失败，流程终止"
            return result

        converted_records = resp2.result.get("converted_records", [])
        result.issues.extend(resp2.result.get("issues", []))
        current_data = converted_records

        # ─── Step 3: 重复记录检查 ───
        step_num += 1
        req3 = ToolCallRequest(
            tool_name="duplicate_checker",
            parameters={
                "records": current_data,
                "key_field": "sample_id",
                "compare_fields": ["SMILES", "property_value", "unit"],
            },
        )
        resp3 = self.registry.call(req3)
        result.execution_records.append(
            ExecutionRecord(step=step_num, step_name="check_duplicates", request=req3, response=resp3)
        )

        if resp3.status == CallStatus.NEEDS_CONFIRMATION:
            # 存在冲突，需要用户确认
            if user_decision is None:
                # 返回确认请求，等待用户决策
                result.status = CallStatus.NEEDS_CONFIRMATION
                result.confirmation_request = resp3.confirmation_request
                result.issues.append(
                    f"发现 {len(resp3.confirmation_request.get('conflicts', []))} 组冲突记录"
                )
                result.final_message = resp3.confirmation_request.get("message", "需要用户确认")
                # 附带当前数据以便用户查看
                result.cleaned_data = resp3.result.get("unique_records", [])
                return result
            else:
                # 用户已给出决策，执行去重
                conflicts = resp3.result.get("conflicts", [])
                result.issues.append(
                    f"冲突已解决: 用户选择 '{user_decision}'，涉及 {len(conflicts)} 组冲突"
                )
                unique_records = self._resolve_conflicts(
                    current_data, conflicts, user_decision
                )
                result.cleaned_data = unique_records
        else:
            result.cleaned_data = resp3.result.get("unique_records", [])
            if resp3.result.get("duplicates"):
                dup_count = len(resp3.result["duplicates"])
                result.issues.append(f"发现 {dup_count} 组完全重复记录，已自动去重")

        result.final_message = f"处理完成: 输入 {len(records)} 条，输出 {len(result.cleaned_data)} 条，问题 {len(result.issues)} 条"
        return result

    def _resolve_conflicts(
        self, records: list[dict], conflicts: list[dict], decision: str
    ) -> list[dict]:
        """根据用户决策解决冲突，同时去除完全重复记录"""
        conflict_keys = {c["key"] for c in conflicts}
        result: list[dict] = []
        seen: set = set()

        for rec in records:
            key = rec.get("sample_id")
            if key in conflict_keys:
                if key in seen:
                    if decision == "keep_both":
                        result.append({**rec, "_conflict_resolved": True})
                    continue
                seen.add(key)
                if decision == "keep_last":
                    continue
                else:
                    result.append(rec)
            else:
                # 非冲突记录：去重（保留首次出现）
                if key not in seen:
                    seen.add(key)
                    result.append(rec)

        # keep_last: 补上冲突记录的最后一条
        if decision == "keep_last":
            for rec in reversed(records):
                key = rec.get("sample_id")
                if key in conflict_keys and key not in {r.get("sample_id") for r in result}:
                    result.append(rec)
                    break

        return result
