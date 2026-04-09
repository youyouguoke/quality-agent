"""
质量管理 AI Agent 系统 - Agent 编排层（性能优化版）

核心优化：单层 Agent 架构，直接调用工具查询数据，避免两层 LLM 串行调用。
- 之前：主控 LLM(~5s) -> 子Agent LLM(~5s x N轮) = 30-60s
- 现在：单 Agent LLM(~5s x N轮) = 10-25s
"""
import json
import logging
import re
import uuid
from typing import Any, Optional

from openai import OpenAI

from config import LLM_CONFIG, TABLE_SCHEMAS, UNAVAILABLE_TABLES
from models import AgentStep, ChatMessage, ToolCallRecord
from skill_manager import build_skill_prompt, match_skills
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

BASE_SYSTEM_PROMPT = """你是质量管理AI Agent，擅长分析质量数据资产。你可以直接调用工具查询数据库并给出分析。

## 你的能力
1. **SN溯源**：通过SN查询生产/出货/客退全链路数据和关键物料 → 优先用 `sn_full_trace`
2. **供应商分析**：查询IQC数据、月度趋势、横向对比 → 优先用 `supplier_overview`
3. **SKU分析**：查询SKU维度的质量数据和月度趋势 → 优先用 `sku_overview`
4. **代工厂分析**：查询工厂全流程质量数据 → 优先用 `factory_overview`
5. **物料分析**：查询物料进货/退货/合格率 → 用 `query_table` 查 part_quality 系列表
6. **客退分析**：查询客退数据做多维度统计 → 优先用 `return_overview`，它会返回7个维度的结构化数据
7. **根因分析**：基于NG记录和客退数据做故障原因统计 → 用 `aggregate_query` 做分组统计

## 工作原则
- 优先使用组合工具（sn_full_trace/supplier_overview/return_overview等）一次获取多维度数据，减少调用次数
- 每次工具调用后如果数据已足够回答问题，立即给出分析结论，不要多余调用
- 所有占比都要计算并展示百分比
- 用中文回答，结构清晰

## 可用数据表
{data_context}
"""

# 反思 prompt：分析完成后让 LLM 评估是否需要改进 Skill
REFLECTION_PROMPT = """请回顾本次分析过程，思考以下问题并以 JSON 格式回答：
1. 本次分析中是否有新发现的领域知识或判断标准？（如某个指标的正常范围、某类问题的常见原因等）
2. 分析流程是否有可以优化的地方？（如某个步骤多余、或者缺少某个步骤）
3. 输出格式是否需要调整？

请严格按以下 JSON 格式回答（如果没有改进建议，should_update 设为 false）：
```json
{
    "should_update": true/false,
    "skill_name": "技能名称（如果需要更新）",
    "new_knowledge": "新发现的知识（追加到现有知识后面，如果没有则为空字符串）",
    "improvement_note": "改进说明（简要描述改了什么）"
}
```
只返回 JSON，不要其他内容。"""


# ======================== 核心执行逻辑 ========================

MAX_TOOL_ROUNDS = 5  # 减少最大轮数，加快响应


def _try_reflect_and_update(client: OpenAI, messages: list[dict], matched_skills: list[dict]):
    """
    反思步骤：分析完成后让 LLM 评估是否需要改进 Skill。
    异步执行，不影响主流程返回速度。失败时静默忽略。
    """
    if not matched_skills:
        return

    try:
        reflect_messages = messages.copy()
        reflect_messages.append({"role": "user", "content": REFLECTION_PROMPT})

        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=reflect_messages,
            temperature=0.3,
            max_tokens=500,
        )
        reflect_text = response.choices[0].message.content or ""

        # 提取 JSON
        json_match = re.search(r"\{[\s\S]*\}", reflect_text)
        if not json_match:
            return

        reflection = json.loads(json_match.group())
        if not reflection.get("should_update"):
            return

        skill_name = reflection.get("skill_name", "")
        new_knowledge = reflection.get("new_knowledge", "")
        improvement_note = reflection.get("improvement_note", "")

        if not skill_name or not new_knowledge:
            return

        # 找到对应 Skill 并更新
        from skill_manager import append_improvement_log, update_skill

        target_skill = None
        for s in matched_skills:
            if s["name"] == skill_name:
                target_skill = s
                break

        if target_skill is None:
            return

        # 追加新知识到现有知识末尾
        current_knowledge = target_skill.get("knowledge", "")
        updated_knowledge = current_knowledge.rstrip() + "\n" + new_knowledge
        update_skill(skill_name, "知识", updated_knowledge)

        # 更新版本号和改进日志
        old_version = target_skill.get("version", "1.0")
        parts = old_version.split(".")
        new_version = f"{parts[0]}.{int(parts[-1]) + 1}"
        append_improvement_log(skill_name, new_version, improvement_note)

        logger.info("Skill [%s] 已自动更新至 v%s: %s", skill_name, new_version, improvement_note)

    except Exception as e:
        logger.debug("反思更新 Skill 失败（不影响主流程）: %s", e)


def run_master_agent(
    query: str,
    session_id: Optional[str] = None,
    history: Optional[list[ChatMessage]] = None,
    user: Optional[str] = None,
) -> dict[str, Any]:
    """
    单层Agent入口：直接理解问题、调用工具、分析数据、返回结果。

    Args:
        user: 当前登录用户（来自请求头 smartmi-ua），透传给 MCP 调用。
    """
    if session_id is None:
        session_id = str(uuid.uuid4())

    client = get_llm_client()
    tool_records: list[ToolCallRecord] = []

    # 匹配相关 Skill
    matched_skills = match_skills(query)
    skill_prompt = build_skill_prompt(matched_skills)
    if matched_skills:
        logger.info("匹配到 Skill: %s", [s["name"] for s in matched_skills])

    # 构建 system prompt = 基础 prompt + 数据上下文 + 匹配的 Skill
    system_prompt = BASE_SYSTEM_PROMPT.format(data_context=_build_all_data_context())
    if skill_prompt:
        system_prompt += "\n" + skill_prompt

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

            # 反思：分析是否有可以改进 Skill 的地方
            _try_reflect_and_update(client, messages + [{"role": "assistant", "content": answer}], matched_skills)

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
            result = execute_tool(func_name, func_args, user=user)

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

    # 反思：分析是否有可以改进 Skill 的地方
    _try_reflect_and_update(client, messages + [{"role": "assistant", "content": answer}], matched_skills)

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
