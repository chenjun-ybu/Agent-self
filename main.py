"""
main.py — 工程实验主程序（LLM 驱动版）

使用 DeepSeek LLM + Agent 驱动化学数据处理 Skill。
每一步出现异常/错误时，LLM 分析问题并请求用户确认。

运行方式：
    python main.py

API 密钥配置：
    方式 1: 复制 config.example.json 为 config.json，填入 api_key
    方式 2: 设置环境变量 DEEPSEEK_API_KEY
"""

import json
import os
import sys

from llm_client import LLMClient
from agent import Agent
from protocol import CallStatus

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")


def load_data(filename: str) -> list[dict]:
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def print_separator(title: str):
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}")


def save_result(filename: str, data: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  → 结果已保存: {path}")


def main():
    # 初始化 LLM 客户端
    llm = LLMClient()

    print(f"{'=' * 70}")
    print(f"  科研智能体工程实验（三）— LLM 驱动版")
    print(f"{'=' * 70}")
    print(f"\nLLM 配置:")
    print(f"  模型: {llm.model}")
    print(f"  API 端点: {llm.base_url}")
    print(f"  密钥状态: {'✓ 已配置' if llm.is_ready() else '✗ 未配置'}")

    if not llm.is_ready():
        print(f"\n  ⚠ API 密钥未配置！请通过以下方式设置：")
        print(f"    1. 复制 config.example.json 为 config.json，填入 api_key")
        print(f"    2. 或设置环境变量: set DEEPSEEK_API_KEY=sk-xxxx")
        print(f"\n  程序退出。请配置后重新运行。")
        sys.exit(1)

    # 创建 Agent
    agent = Agent(llm, interactive=True)

    print(f"\n已注册工具:")
    for tool in agent.registry.list_tools():
        print(f"  - {tool['name']}: {tool['description']}")

    # ════════════════════════════════════════════════════════
    # 场景 1: 正常调用 — 第一批数据
    # ════════════════════════════════════════════════════════
    print_separator("场景 1: 正常调用 — 第一批数据 (batch1.json)")
    batch1 = load_data("batch1.json")
    print(f"输入数据 ({len(batch1)} 条):")
    for rec in batch1:
        print(f"  {rec}")

    # 每个场景创建新的 Agent 以重置状态
    agent1 = Agent(llm, interactive=True)
    result1 = agent1.process_data(batch1, target_unit="C", property_type="temperature")
    print(f"\n--- 场景 1 结果 ---")
    print(f"状态: {result1.status.value}")
    print(f"消息: {result1.final_message}")
    print(f"输出数据 ({len(result1.cleaned_data)} 条):")
    for rec in result1.cleaned_data:
        print(f"  {rec}")
    save_result("scenario1_batch1_result.json", result1.to_dict())

    # ════════════════════════════════════════════════════════
    # 场景 2: 正常调用 — 第二批数据（同一 Skill，不修改流程）
    # ════════════════════════════════════════════════════════
    print_separator("场景 2: 正常调用 — 第二批数据 (batch2.json)")
    batch2 = load_data("batch2.json")
    print(f"输入数据 ({len(batch2)} 条):")
    for rec in batch2:
        print(f"  {rec}")

    agent2 = Agent(llm, interactive=True)
    result2 = agent2.process_data(batch2, target_unit="C", property_type="temperature")
    print(f"\n--- 场景 2 结果 ---")
    print(f"状态: {result2.status.value}")
    print(f"消息: {result2.final_message}")
    print(f"输出数据 ({len(result2.cleaned_data)} 条):")
    for rec in result2.cleaned_data:
        print(f"  {rec}")
    save_result("scenario2_batch2_result.json", result2.to_dict())

    # ════════════════════════════════════════════════════════
    # 场景 3: 错误调用 — 无效 SMILES / 未知单位 / 缺失字段
    # 每个异常都会触发 LLM 分析 + 用户确认
    # ════════════════════════════════════════════════════════
    print_separator("场景 3: 错误调用 — 含异常的数据 (error_case.json)")
    error_data = load_data("error_case.json")
    print(f"输入数据 ({len(error_data)} 条):")
    for rec in error_data:
        print(f"  {rec}")

    agent3 = Agent(llm, interactive=True)
    result3 = agent3.process_data(error_data, target_unit="C", property_type="temperature")
    print(f"\n--- 场景 3 结果 ---")
    print(f"状态: {result3.status.value}")
    print(f"消息: {result3.final_message}")
    print(f"问题 ({len(result3.issues)} 条):")
    for issue in result3.issues:
        print(f"  ⚠ {issue}")
    print(f"输出数据 ({len(result3.cleaned_data)} 条):")
    for rec in result3.cleaned_data:
        print(f"  {rec}")
    save_result("scenario3_error_case_result.json", result3.to_dict())

    # ════════════════════════════════════════════════════════
    # 场景 4: 冲突重复记录 — 需要用户确认
    # ════════════════════════════════════════════════════════
    print_separator("场景 4: 冲突重复记录 — 需要用户确认 (confirmation_case.json)")
    confirm_data = load_data("confirmation_case.json")
    print(f"输入数据 ({len(confirm_data)} 条):")
    for rec in confirm_data:
        print(f"  {rec}")

    agent4 = Agent(llm, interactive=True)
    result4 = agent4.process_data(confirm_data, target_unit="C", property_type="temperature")
    print(f"\n--- 场景 4 结果 ---")
    print(f"状态: {result4.status.value}")
    print(f"消息: {result4.final_message}")
    print(f"问题 ({len(result4.issues)} 条):")
    for issue in result4.issues:
        print(f"  ⚠ {issue}")
    print(f"输出数据 ({len(result4.cleaned_data)} 条):")
    for rec in result4.cleaned_data:
        print(f"  {rec}")
    save_result("scenario4_confirmation_result.json", result4.to_dict())

    # ════════════════════════════════════════════════════════
    # 汇总工具调用日志
    # ════════════════════════════════════════════════════════
    print_separator("工具调用日志汇总")
    all_logs = []
    for agent_obj, label in [
        (agent1, "场景1"), (agent2, "场景2"),
        (agent3, "场景3"), (agent4, "场景4"),
    ]:
        for rec in agent_obj.execution_records:
            entry = {"scenario": label, **rec.to_dict()}
            all_logs.append(entry)
        all_logs.extend(
            {"scenario": label, **log}
            for log in agent_obj.registry.get_call_log()
            if log not in all_logs
        )

    print(f"总调用次数: {len(all_logs)}")
    for i, entry in enumerate(all_logs):
        print(f"\n调用 #{i+1} [{entry.get('scenario', '?')}]:")
        if "step" in entry:
            print(f"  Step {entry['step']}: {entry['step_name']}")
            print(f"  Request: {json.dumps(entry['request'], ensure_ascii=False)}")
            print(f"  Response: {json.dumps(entry['response'], ensure_ascii=False)}")
        else:
            print(f"  {json.dumps(entry, ensure_ascii=False)}")

    save_result("tool_call_log.json", {
        "total_calls": len(all_logs),
        "calls": all_logs,
    })

    print(f"\n{'=' * 70}")
    print(f"  所有场景执行完成。结果已保存到 output/ 目录。")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
