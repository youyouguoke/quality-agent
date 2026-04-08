"""
质量管理 AI Agent 系统 - Agent 编排层（性能优化版）

核心优化：单层 Agent 架构，直接调用工具查询数据，避免两层 LLM 串行调用。
- 之前：主控 LLM(~5s) -> 子Agent LLM(~5s x N轮) = 30-60s
- 现在：单 Agent LLM(~5s x N轮) = 10-25s
"""
import json
import logging
import uuid
from typing import Any, Optional

from openai import OpenAI

from config import LLM_CONFIG, TABLE_SCHEMAS, UNAVAILABLE_TABLES
from models import AgentStep, ChatMessage, ToolCallRecord
from tools import OPENAI_TOOLS_SCHEMA, execute_tool

logger = logging.getLogger(__name__)

# ======================== LLM 客户端 ========================

_client: Optional[OpenAI] = None


def get_llm_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=LLM_CONFIG["api_key"],
            base_url=LLM_CONFIG["base_url"],
            timeout=120,
        )
    return _client


# ======================== 会话管理 ========================

_sessions: dict[str, list[dict]] = {}
MAX_HISTORY = 20


def get_session(session_id: str) -> list[dict]:
    if session_id not in _sessions:
        _sessions[session_id] = []
    return _sessions[session_id]


def save_to_session(session_id: str, role: str, content: str):
    history = get_session(session_id)
    history.append({"role": role, "content": content})
    if len(history) > MAX_HISTORY:
        _sessions[session_id] = history[-MAX_HISTORY:]


def clear_session(session_id: str):
    _sessions.pop(session_id, None)


# ======================== 构建数据资产上下文 ========================

def _build_all_data_context() -> str:
    """构建全部可用表的上下文描述"""
    lines = []
    for key, schema in TABLE_SCHEMAS.items():
        available = "可用" if key not in UNAVAILABLE_TABLES else "不可用"
        lines.append(f"- 表 `{key}`（{available}）：{schema['description']}")
        mapping = schema.get("column_mapping", {})
        if mapping:
            mapping_str = ", ".join(f"{en}({zh})" for en, zh in mapping.items())
            lines.append(f"  字段：{mapping_str}")
    return "\n".join(lines)


# ======================== 统一 Agent Prompt ========================

SYSTEM_PROMPT = """你是质量管理AI Agent，擅长分析质量数据资产。你可以直接调用工具查询数据库并给出分析。

## 你的能力
1. **SN溯源**：通过SN查询生产/出货/客退全链路数据和关键物料 → 优先用 `sn_full_trace`
2. **供应商分析**：查询IQC数据、月度趋势、横向对比 → 优先用 `supplier_overview`
3. **SKU分析**：查询SKU维度的质量数据和月度趋势 → 优先用 `sku_overview`
4. **代工厂分析**：查询工厂全流程质量数据 → 优先用 `factory_overview`
5. **物料分析**：查询物料进货/退货/合格率 → 用 `query_table` 查 part_quality 系列表
6. **客退分析**：查询客退数据做多维度统计 → 优先用 `return_overview`，它会返回7个维度的结构化数据
7. **根因分析**：基于NG记录和客退数据做故障原因统计 → 用 `aggregate_query` 做分组统计

## 客退分析报告格式要求
当用户要求客退分析时，调用 `return_overview` 获取数据后，必须严格按以下8个章节输出报告：

### 一、整体概况
用表格展示：产品名称、生产工厂、维修工厂、退货数量、复测完成率、返修完成率
- 复测完成率 = 已复测+待翻新+已翻新+已完成的数量 / 退货总数
- 返修完成率 = 已翻新+已完成的数量 / 退货总数

### 二、受理原因分析
数据已按四分类（质量、7无、付费换新、其他）汇总好，用表格展示各分类的数量和占比，并展示每个分类下的明细原因。

### 三、复测结果分析
数据仅包含有复测结果的记录（排除未复测的），展示TOP5复测结果的数量和占比，其余归入"其他"。

### 四、不良原因分析
仅统计有复测结果的记录。展示TOP5不良原因的数量和占比，其余归入"其他"。注意数据已做多值拆分统计。空值已排除。

### 五、不良物料分析
仅统计有复测结果的记录。展示TOP5不良物料的数量和占比，其余归入"其他"。注意数据已做多值拆分统计。空值已排除。

### 六、责任归属分析
仅统计有复测结果的记录。展示TOP10责任归属的数量和占比，其余归入"其他"。注意数据已做多值拆分统计。

### 七、处理状况分析
用表格展示各状态的数量和占比。

### 八、核心结论与建议
基于以上7个维度的数据，总结3-5条核心发现和改善建议。

## 工作原则
- 优先使用组合工具（sn_full_trace/supplier_overview/return_overview等）一次获取多维度数据，减少调用次数
- 每次工具调用后如果数据已足够回答问题，立即给出分析结论，不要多余调用
- 所有占比都要计算并展示百分比
- 用中文回答，结构清晰

## 可用数据表
{data_context}
"""


# ======================== 核心执行逻辑 ========================

MAX_TOOL_ROUNDS = 5  # 减少最大轮数，加快响应


def run_master_agent(
    query: str,
    session_id: Optional[str] = None,
    history: Optional[list[ChatMessage]] = None,
) -> dict[str, Any]:
    """
    单层Agent入口：直接理解问题、调用工具、分析数据、返回结果。
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    client = get_llm_client()
    tool_records: list[ToolCallRecord] = []

    # 构建 system prompt（含数据资产上下文）
    system_prompt = SYSTEM_PROMPT.format(data_context=_build_all_data_context())

    messages = [{"role": "system", "content": system_prompt}]

    # 加入历史对话
    if history:
        for msg in history[-6:]:
            messages.append({"role": msg.role.value, "content": msg.content})
    else:
        session_history = get_session(session_id)
        for msg in session_history[-6:]:
            messages.append(msg)

    messages.append({"role": "user", "content": query})

    # Function Calling 循环
    for round_idx in range(MAX_TOOL_ROUNDS):
        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=messages,
            tools=OPENAI_TOOLS_SCHEMA,
            temperature=LLM_CONFIG["temperature"],
            max_tokens=LLM_CONFIG["max_tokens"],
        )
        msg = response.choices[0].message

        # 无工具调用 → 最终回答
        if not msg.tool_calls:
            answer = msg.content or ""
            save_to_session(session_id, "user", query)
            save_to_session(session_id, "assistant", answer)

            return {
                "answer": answer,
                "session_id": session_id,
                "agent_used": "quality_agent",
                "steps": [AgentStep(
                    agent="quality_agent",
                    action=query,
                    tool_calls=tool_records,
                )] if tool_records else [],
                "data": None,
                "metadata": {"rounds": round_idx + 1},
            }

        # 处理工具调用
        messages.append(msg.model_dump())

        for tool_call in msg.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                func_args = {}

            logger.info("调用工具: %s(%s)", func_name, func_args)
            result = execute_tool(func_name, func_args)

            # 截断过长结果
            if len(result) > 6000:
                result = result[:6000] + "\n...(数据已截断)"

            tool_records.append(ToolCallRecord(
                tool_name=func_name,
                arguments=func_args,
                result_summary=result[:200] + "..." if len(result) > 200 else result,
            ))

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    # 达到最大轮数，强制总结
    messages.append({"role": "user", "content": "请根据已获取的数据直接给出分析结论。"})
    response = client.chat.completions.create(
        model=LLM_CONFIG["model"],
        messages=messages,
        temperature=LLM_CONFIG["temperature"],
        max_tokens=LLM_CONFIG["max_tokens"],
    )
    answer = response.choices[0].message.content or ""
    save_to_session(session_id, "user", query)
    save_to_session(session_id, "assistant", answer)

    return {
        "answer": answer,
        "session_id": session_id,
        "agent_used": "quality_agent",
        "steps": [AgentStep(
            agent="quality_agent",
            action=query,
            tool_calls=tool_records,
        )] if tool_records else [],
        "data": None,
        "metadata": {"rounds": MAX_TOOL_ROUNDS},
    }
