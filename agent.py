"""
agent.py — LLM 驱动的科研智能体

Agent 编排 LLM + Skill + Protocol + 用户确认：
  1. LLM 分析输入数据，生成处理意图
  2. 按步骤执行 Skill 中的工具调用
  3. 每一步出现异常/错误时：
     a. 将异常发送给 LLM 分析
     b. LLM 生成自然语言解释和建议操作
     c. 向用户展示 LLM 分析结果，请求用户确认
     d. 根据用户决策继续或终止
  4. LLM 生成最终处理报告

关键设计：
  - LLM 负责"理解与建议"（意图生成）
  - Skill 负责"怎么做"（程序性知识）
  - Protocol 负责"调用约束与确认"（交互结构）
  - 用户在每次异常时都有确认权
"""

import json
import sys
from typing import Optional

from llm_client import LLMClient
from protocol import (
    ToolCallRequest, ToolCallResponse, CallStatus,
    ExecutionRecord, SkillResult,
)
from tool_registry import create_default_registry

SYSTEM_PROMPT = """你是一个化学数据处理智能体，负责分析化学数据的处理结果并给出建议。

你的职责：
1. 分析数据处理过程中发现的异常和错误
2. 用简洁的中文解释每条问题的原因
3. 给出建议的处理方式

输出格式要求：
- 先用 1-2 句话概括问题
- 逐条分析每个具体问题
- 最后给出建议操作

保持专业、简洁、准确。"""


class Agent:
    """LLM 驱动的科研智能体"""

    def __init__(self, llm: LLMClient, interactive: bool = True):
        self.llm = llm
        self.registry = create_default_registry()
        self.interactive = interactive and sys.stdin.isatty()
        self.conversation: list[dict] = []
        self.execution_records: list[ExecutionRecord] = []

    # ──────────────────────────────────────
    #  用户交互
    # ──────────────────────────────────────
    def _ask_user(
        self,
        llm_analysis: str,
        issues: list[dict],
        options: list[str],
        option_labels: dict[str, str],
    ) -> str:
        """
        向用户展示 LLM 分析结果和问题，请求用户确认。

        Args:
            llm_analysis:  LLM 对问题的分析文本
            issues:        具体问题列表
            options:       可选操作列表
            option_labels: 操作的中文标签

        Returns:
            用户选择的操作名称
        """
        print(f"\n{'━' * 60}")
        print(f"  ⚠ 检测到异常 — 需要用户确认")
        print(f"{'━' * 60}")

        # 展示 LLM 分析
        print(f"\n【LLM 分析】")
        print(llm_analysis)

        # 展示具体问题
        print(f"\n【问题详情】")
        for i, issue in enumerate(issues):
            print(f"  {i+1}. {issue}")

        # 展示选项
        print(f"\n【请选择处理方式】")
        for i, opt in enumerate(options):
            print(f"  {i+1}. {option_labels.get(opt, opt)}")

        if not self.interactive:
            print(f"\n  [非交互模式] 自动选择: {options[0]}")
            return options[0]

        while True:
            try:
                choice = input(
                    f"\n  请输入选项编号 (1-{len(options)})，或输入 'abort' 终止: "
                ).strip()
                if choice.lower() in ("abort", "exit", "quit"):
                    return "abort"
                num = int(choice)
                if 1 <= num <= len(options):
                    selected = options[num - 1]
                    print(f"  >>> 用户选择: {selected}\n")
                    return selected
                print(f"  请输入 1 到 {len(options)} 之间的数字")
            except ValueError:
                print(f"  无效输入，请输入数字")
            except (EOFError, KeyboardInterrupt):
                print(f"\n  [输入中断] 自动选择: {options[0]}")
                return options[0]

    # ──────────────────────────────────────
    #  LLM 调用
    # ──────────────────────────────────────
    def _llm_analyze(self, context: str) -> str:
        """调用 LLM 分析问题"""
        try:
            reply = self.llm.analyze(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=context,
            )
            return reply
        except RuntimeError as e:
            return f"[LLM 调用失败] {e}"

    def _llm_initial_analysis(self, records: list[dict]) -> str:
        """LLM 分析输入数据"""
        data_str = json.dumps(records, ensure_ascii=False, indent=2)
        prompt = f"""请分析以下化学数据，指出可能的问题（如无效SMILES、单位不一致、重复记录等）：

{data_str}

请简要分析数据质量和潜在问题。"""
        return self._llm_analyze(prompt)

    def _llm_final_summary(self, result: SkillResult) -> str:
        """LLM 生成最终处理报告"""
        summary_data = {
            "输入记录数": self._input_count,
            "输出记录数": len(result.cleaned_data),
            "问题数量": len(result.issues),
            "问题列表": result.issues,
            "输出数据": result.cleaned_data,
        }
        prompt = f"""请根据以下处理结果生成简要报告：

{json.dumps(summary_data, ensure_ascii=False, indent=2)}

请总结处理过程和结果。"""
        return self._llm_analyze(prompt)

    # ──────────────────────────────────────
    #  工具执行 + 异常确认
    # ──────────────────────────────────────
    def _execute_step(
        self,
        step: int,
        step_name: str,
        tool_name: str,
        parameters: dict,
    ) -> ToolCallResponse:
        """执行一个工具步骤，如果有异常则请求用户确认"""
        req = ToolCallRequest(tool_name=tool_name, parameters=parameters)
        resp = self.registry.call(req)

        self.execution_records.append(
            ExecutionRecord(
                step=step, step_name=step_name,
                request=req, response=resp,
            )
        )

        return resp

    def _handle_step_issues(
        self,
        step_name: str,
        resp: ToolCallResponse,
        issues: list[str],
        records: list[dict],
        issue_type: str,
    ) -> tuple[list[dict], bool]:
        """
        处理步骤中的异常：LLM 分析 → 用户确认。

        Returns:
            (处理后的记录列表, 是否继续)
        """
        if not issues:
            return records, True

        # 调用 LLM 分析异常
        context = f"""在"{step_name}"步骤中发现以下问题：

问题列表:
{chr(10).join(f'- {i}' for i in issues)}

当前数据:
{json.dumps(records, ensure_ascii=False, indent=2)}

请分析这些问题并给出建议。"""

        llm_analysis = self._llm_analyze(context)

        # 构造选项
        if issue_type == "smiles":
            options = ["skip_invalid", "abort"]
            labels = {
                "skip_invalid": "跳过无效记录，继续处理有效记录",
                "abort": "终止整个处理流程",
            }
        elif issue_type == "unit":
            options = ["skip_unknown", "abort"]
            labels = {
                "skip_unknown": "跳过未知单位的记录，继续处理",
                "abort": "终止整个处理流程",
            }
        elif issue_type == "duplicate":
            options = ["keep_first", "keep_last", "keep_both", "abort"]
            labels = {
                "keep_first": "保留第一条记录",
                "keep_last": "保留最后一条记录",
                "keep_both": "全部保留（标记来源）",
                "abort": "终止处理流程",
            }
        else:
            options = ["continue", "abort"]
            labels = {
                "continue": "继续处理",
                "abort": "终止流程",
            }

        issue_dicts = [str(i) for i in issues]
        user_choice = self._ask_user(llm_analysis, issue_dicts, options, labels)

        if user_choice == "abort":
            return [], False

        # 根据用户决策处理
        if issue_type == "smiles":
            # skip_invalid: 只保留有效记录（已在 resp.result 中）
            return resp.result.get("valid_records", records), True

        elif issue_type == "unit":
            # skip_unknown: 只保留已转换的记录
            return resp.result.get("converted_records", records), True

        elif issue_type == "duplicate":
            # 用户选择冲突解决策略
            conflicts = resp.result.get("conflicts", [])
            unique = resp.result.get("unique_records", records)
            if conflicts:
                resolved = self._resolve_conflicts(records, conflicts, user_choice)
                return resolved, True
            return unique, True

        return records, True

    def _resolve_conflicts(
        self, records: list[dict], conflicts: list[dict], decision: str
    ) -> list[dict]:
        """根据用户决策解决冲突"""
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
                if key not in seen:
                    seen.add(key)
                    result.append(rec)

        if decision == "keep_last":
            for rec in reversed(records):
                key = rec.get("sample_id")
                if key in conflict_keys and key not in {r.get("sample_id") for r in result}:
                    result.append(rec)
                    break

        return result

    # ──────────────────────────────────────
    #  主流程
    # ──────────────────────────────────────
    def process_data(
        self,
        records: list[dict],
        target_unit: str = "C",
        property_type: str = "temperature",
    ) -> SkillResult:
        """
        Agent 主流程：LLM 分析 → 工具执行 → 异常确认 → 最终报告

        每一步出现异常都请求用户确认，而非仅最后一步。
        """
        self._input_count = len(records)
        result = SkillResult(
            skill_name="chemical_data_processing",
            status=CallStatus.SUCCESS,
        )

        # 0) LLM 初始分析
        print(f"\n{'─' * 60}")
        print(f"  LLM 初始数据分析")
        print(f"{'─' * 60}")
        llm_initial = self._llm_initial_analysis(records)
        print(llm_initial)

        current_data = list(records)

        # 1) Step 1: SMILES 校验
        print(f"\n{'─' * 60}")
        print(f"  Step 1: SMILES 校验")
        print(f"{'─' * 60}")
        resp1 = self._execute_step(
            step=1, step_name="validate_smiles",
            tool_name="smiles_validator",
            parameters={
                "records": current_data,
                "required_fields": ["sample_id", "SMILES", "property_value", "unit"],
            },
        )
        print(f"  状态: {resp1.status.value}")
        if resp1.result:
            print(f"  有效记录: {len(resp1.result.get('valid_records', []))} / {len(current_data)}")

        issues1 = resp1.result.get("issues", []) if resp1.result else []
        if issues1 or resp1.status == CallStatus.ERROR:
            # 有异常 → LLM 分析 → 用户确认
            valid, cont = self._handle_step_issues(
                "SMILES 校验", resp1, issues1,
                current_data, "smiles",
            )
            if not cont:
                result.status = CallStatus.ERROR
                result.issues = issues1
                result.final_message = "用户选择终止流程"
                result.execution_records = self.execution_records
                return result
            current_data = valid
            result.issues.extend(issues1)
        else:
            current_data = resp1.result.get("valid_records", current_data)

        if not current_data:
            result.status = CallStatus.ERROR
            result.issues.append("SMILES 校验后无有效记录")
            result.execution_records = self.execution_records
            result.final_message = "所有记录无效，流程终止"
            return result

        # 2) Step 2: 单位转换
        print(f"\n{'─' * 60}")
        print(f"  Step 2: 单位转换 → {target_unit}")
        print(f"{'─' * 60}")
        resp2 = self._execute_step(
            step=2, step_name="convert_units",
            tool_name="unit_converter",
            parameters={
                "records": current_data,
                "target_unit": target_unit,
                "property_type": property_type,
            },
        )
        print(f"  状态: {resp2.status.value}")
        if resp2.result:
            print(f"  转换成功: {len(resp2.result.get('converted_records', []))} / {len(current_data)}")

        issues2 = resp2.result.get("issues", []) if resp2.result else []
        if issues2 or resp2.status == CallStatus.ERROR:
            converted, cont = self._handle_step_issues(
                "单位转换", resp2, issues2,
                current_data, "unit",
            )
            if not cont:
                result.status = CallStatus.ERROR
                result.issues.extend(issues2)
                result.final_message = "用户选择终止流程"
                result.execution_records = self.execution_records
                return result
            current_data = converted
            result.issues.extend(issues2)
        else:
            current_data = resp2.result.get("converted_records", current_data)

        if not current_data:
            result.status = CallStatus.ERROR
            result.issues.append("单位转换后无有效记录")
            result.execution_records = self.execution_records
            result.final_message = "所有记录单位转换失败，流程终止"
            return result

        # 3) Step 3: 重复记录检查
        print(f"\n{'─' * 60}")
        print(f"  Step 3: 重复记录检查")
        print(f"{'─' * 60}")
        resp3 = self._execute_step(
            step=3, step_name="check_duplicates",
            tool_name="duplicate_checker",
            parameters={
                "records": current_data,
                "key_field": "sample_id",
                "compare_fields": ["SMILES", "property_value", "unit"],
            },
        )
        print(f"  状态: {resp3.status.value}")
        if resp3.result:
            dups = resp3.result.get("duplicates", [])
            conflicts = resp3.result.get("conflicts", [])
            print(f"  完全重复: {len(dups)} 组, 冲突记录: {len(conflicts)} 组")

        # 重复和冲突都是异常，都需要用户确认
        all_issues_3 = []
        if resp3.result:
            dups = resp3.result.get("duplicates", [])
            conflicts = resp3.result.get("conflicts", [])
            for d in dups:
                all_issues_3.append(
                    f"完全重复: sample_id={d['key']} (所有字段一致，已自动去重)"
                )
            for c in conflicts:
                diff_str = ", ".join(
                    f"{k}({v['existing']} vs {v['new']})"
                    for k, v in c.get("conflict_fields", {}).items()
                )
                all_issues_3.append(
                    f"冲突记录: sample_id={c['key']} — {diff_str}"
                )

        if resp3.status == CallStatus.NEEDS_CONFIRMATION or all_issues_3:
            resolved, cont = self._handle_step_issues(
                "重复记录检查", resp3, all_issues_3,
                current_data, "duplicate",
            )
            if not cont:
                result.status = CallStatus.ERROR
                result.issues.extend(all_issues_3)
                result.final_message = "用户选择终止流程"
                result.execution_records = self.execution_records
                return result
            current_data = resolved
            result.issues.extend(all_issues_3)
        else:
            current_data = resp3.result.get("unique_records", current_data)

        result.cleaned_data = current_data
        result.execution_records = self.execution_records
        result.status = CallStatus.SUCCESS
        result.final_message = (
            f"处理完成: 输入 {self._input_count} 条, 输出 {len(current_data)} 条, "
            f"问题 {len(result.issues)} 条"
        )

        # 4) LLM 最终报告
        print(f"\n{'─' * 60}")
        print(f"  LLM 最终处理报告")
        print(f"{'─' * 60}")
        llm_summary = self._llm_final_summary(result)
        print(llm_summary)

        return result
