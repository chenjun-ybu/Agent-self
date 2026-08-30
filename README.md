# 化学数据处理 Skill — 科研智能体工程实验（三）

## 项目概述

本项目将化学数据处理流程外部化为可复用的 **Skill**，使用结构化 **Protocol** 规范工具调用和用户确认，通过 **LLM (DeepSeek-v4-flash)** 驱动 Agent 在每一步出现异常时分析问题并请求用户确认，展示 Skills 与 Protocols 如何在 Harness 中将任务意图转化为可执行、可约束的行动。

### 核心概念

| 概念 | 角色 | 本项目对应 |
|------|------|------------|
| **Tool** | 提供具体操作能力 | `tools.py` — SMILES 校验器、单位转换器、重复检查器 |
| **Skill** | 组织完成一类任务的方法 | `skill_executor.py` + `skills/chemical_data_processing.yaml` |
| **Protocol** | 规定能力如何被发现、调用、传递结果并接受约束 | `protocol.py` + `tool_registry.py` |
| **LLM** | 生成意图、分析异常、建议操作 | `llm_client.py` — DeepSeek-v4-flash API 封装 |
| **Agent** | 编排 LLM + Skill + 用户确认 | `agent.py` — 每步异常都触发 LLM 分析 + 用户确认 |

## 环境配置

### 依赖

- Python 3.10+（标准库即可运行，无需安装第三方包）
- PyYAML（可选，用于加载 Skill YAML 描述文件）

```bash
pip install pyyaml  # 可选
```

### API 密钥配置

LLM 使用 DeepSeek API，密钥通过以下方式配置（优先级从高到低）：

**方式 1：环境变量**
```bash
set DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

**方式 2：配置文件**

复制 `config.example.json` 为 `config.json`，填入 API 密钥：
```json
{
    "api_key": "sk-xxxxxxxxxxxxxxxx",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-v4-flash"
}
```

> `config.json` 已在 `.gitignore` 中排除，不会提交到 GitHub。

### 文件结构

```
chemical_agent/
├── skills/
│   └── chemical_data_processing.yaml   # Skill 描述文件（YAML）
├── data/
│   ├── batch1.json                      # 第一批化学数据（正常）
│   ├── batch2.json                      # 第二批化学数据（正常）
│   ├── error_case.json                  # 含错误的数据（无效SMILES/未知单位/缺失字段）
│   └── confirmation_case.json           # 含冲突重复记录的数据（需用户确认）
├── config.py                            # 配置管理（API 密钥、模型名称）
├── config.example.json                  # 配置文件模板
├── llm_client.py                        # LLM 客户端：DeepSeek API 封装
├── agent.py                             # Agent：LLM 驱动，每步异常都请求用户确认
├── protocol.py                          # Protocol：结构化请求/响应定义
├── tools.py                             # Tool：三个具体操作工具
├── tool_registry.py                     # 统一工具调用接口（ToolRegistry）
├── skill_executor.py                    # Skill 执行器：编排工具完成数据处理流程
├── main.py                              # 主程序：运行四个场景演示
├── .gitignore                           # 排除 config.json 和 output/
├── output/                              # 运行结果输出目录（自动生成）
└── README.md
```

## 运行方式

```bash
cd chemical_agent
python main.py
```

程序将依次执行四个场景。LLM 在每一步分析数据，出现异常时自动请求用户确认（交互式 `input()`）。

### LLM 接口

- **客户端文件**：`llm_client.py`（`LLMClient` 类）
- **API 端点**：`https://api.deepseek.com/v1/chat/completions`
- **模型**：`deepseek-v4-flash`
- **调用方式**：
  ```python
  from llm_client import LLMClient
  client = LLMClient()  # 从 config.json 或环境变量读取密钥
  reply = client.chat([
      {"role": "system", "content": "你是一个化学数据处理助手"},
      {"role": "user", "content": "分析这批数据的问题"},
  ])
  ```

### Skill 文件位置

- **Skill 描述**：`skills/chemical_data_processing.yaml`
- **Skill 执行器**：`skill_executor.py`（`ChemicalDataProcessingSkill` 类）

### 统一工具调用接口

- **接口定义**：`tool_registry.py`（`ToolRegistry` 类）
- **Protocol 定义**：`protocol.py`（`ToolCallRequest` / `ToolCallResponse` / `ExecutionRecord` / `SkillResult`）

## 四个演示场景

| 场景 | 输入数据 | LLM 调用 | 用户确认次数 | 说明 |
|------|----------|----------|-------------|------|
| 1. 正常调用 | `batch1.json`（5条） | 初始分析 + 最终报告 | 0 | SMILES 校验 → K→C 转换 → 去重 |
| 2. 正常调用 | `batch2.json`（5条） | 初始分析 + 最终报告 | 0 | 同一 Skill 处理第二批，不修改流程 |
| 3. 错误调用 | `error_case.json`（5条） | 初始分析 + 2次异常分析 + 最终报告 | **2** | SMILES 无效 → 确认#1；未知单位 → 确认#2 |
| 4. 冲突记录 | `confirmation_case.json`（6条） | 初始分析 + 1次冲突分析 + 最终报告 | **1** | C002 值冲突 → 确认#3 |

### LLM 在每一步的作用

1. **初始分析**：LLM 接收原始数据，分析数据质量和潜在问题
2. **异常分析**：每当工具返回错误/异常时，LLM 分析原因并建议操作
3. **用户确认**：LLM 分析结果展示给用户，用户选择处理方式
4. **最终报告**：LLM 根据处理结果生成自然语言总结

### 三类调用记录

1. **正常执行**：场景 1/2 — 三步工具调用均返回 `success`，LLM 生成数据质量报告
2. **错误返回 + 用户确认**：场景 3 — Step 1 SMILES 无效 → LLM 分析 → 用户确认；Step 2 未知单位 → LLM 分析 → 用户确认
3. **冲突确认**：场景 4 — C002 值冲突 (118.1°C vs 125.0°C) → LLM 分析（正确指出 118.1°C 更接近乙酸文献值）→ 用户选择 `keep_first`

## 输出文件

运行后在 `output/` 目录生成：

| 文件 | 内容 |
|------|------|
| `scenario1_batch1_result.json` | 第一批数据处理结果 |
| `scenario2_batch2_result.json` | 第二批数据处理结果 |
| `scenario3_error_case_result.json` | 错误数据处理结果（含2次用户确认） |
| `scenario4_confirmation_result.json` | 冲突数据处理结果（含1次用户确认） |
| `tool_call_log.json` | 所有工具调用的完整日志 |

