"""
质量管理 AI Agent 系统 - Agent 编排层（性能优化版）

核心优化：单层 Agent 架构，直接调用工具查询数据，避免两层 LLM 串行调用。
- 之前：主控 LLM(~5s) -> 子Agent LLM(~5s x N轮) = 30-60s
- 现在：单 Agent LLM(~5s x N轮) = 10-25s
"""
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

from openai import OpenAI

from config import LLM_CONFIG, TABLE_SCHEMAS, UNAVAILABLE_TABLES
from knowledge_base import build_knowledge_prompt
from memory_store import (
    MEMORY_EXTRACT_PROMPT,
    build_memory_prompt,
    save_memory_from_reflection,
)
from models import AgentStep, ChatMessage, ToolCallRecord
from skill_manager import (
    build_skill_prompt,
    evaluate_and_maybe_rollback,
    generate_skill_from_queries,
    match_skills,
    record_skill_usage,
    record_uncovered_query,
)
from tools import OPENAI_TOOLS_SCHEMA, execute_tool
from user_profile import (
    build_user_prompt,
    record_interaction,
    try_detect_profile_from_query,
    update_profile,
)

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
_session_last_skills: dict[str, list[str]] = {}  # session_id -> 上次使用的 Skill 名称列表
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
    _session_last_skills.pop(session_id, None)


def _detect_followup(session_id: str, query: str) -> bool:
    """
    检测当前问题是否是对上一轮分析的追问。
    追问特征：同一 session 连续提问，且问题涉及上次的分析主题。
    """
    history = get_session(session_id)
    if len(history) < 2:
        return False

    q = query.lower()
    # 追问关键词
    followup_keywords = [
        "再详细", "展开", "具体说", "为什么", "解释一下", "不对", "错了",
        "再看看", "再分析", "换个角度", "还有呢", "其他呢", "补充",
        "刚才", "上面", "上次", "这个", "那个",
    ]
    return any(kw in q for kw in followup_keywords)


def _record_skill_success(session_id: str, matched_skills: list[dict]):
    """记录本轮 Skill 使用成功，并保存到 session 用于下轮追问检测"""
    skill_names = [s["name"] for s in matched_skills]
    _session_last_skills[session_id] = skill_names
    for s in matched_skills:
        record_skill_usage(s["name"], "success", version=s.get("version"))


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
- 查到关键指标（退货率、IQC合格率、直通率等）后，应调用 `baseline_compare` 与基线标准对比，明确标注是正常/预警/严重
- 遇到不确定的质量术语或需要参考历史案例时，调用 `search_knowledge` 检索知识库
- 分析结论中应包含与基线的对比判断，不要只列数字不给评价
- 所有占比都要计算并展示百分比
- 用中文回答，结构清晰

## 可用数据表
{data_context}
"""

# 反思 prompt：分析完成后让 LLM 评估执行质量并改进
REFLECTION_PROMPT = """请回顾本次分析的完整过程（包括工具调用和返回结果），逐项检查以下问题并以 JSON 格式回答：

1. **执行问题**：本次分析过程中是否有工具调用失败、返回空数据、参数匹配失败等问题？（如用户说"5pro"但SKU没匹配到，或MCP返回了空结果）
2. **知识发现**：是否有新发现的领域知识或判断标准值得记录？
3. **流程优化**：分析流程是否有可以优化的地方？
4. **案例沉淀**：是否发现了值得记录的分析案例？

请严格按以下 JSON 格式回答：
```json
{
    "should_update": true/false,
    "skill_name": "技能名称（如果需要更新技能，如'客退多维度分析报告'）",
    "update_section": "要更新的段落（知识/流程）",
    "new_content": "要追加的新内容",
    "improvement_note": "改进说明",
    "agents_md_update": {
        "should_update": true/false,
        "section": "要更新的段落标题（如'SKU 名称映射'）",
        "new_content": "要追加的内容（如新的SKU简称映射行）"
    },
    "new_case": {
        "should_save": true/false,
        "title": "案例标题",
        "content": "案例内容（Markdown格式）"
    },
    "execution_issues": ["问题1描述", "问题2描述"]
}
```
如果没有任何改进建议，所有 should_update/should_save 设为 false。只返回 JSON。"""


# ======================== 核心执行逻辑 ========================

MAX_TOOL_ROUNDS = 5  # 减少最大轮数，加快响应

# AGENTS.md 文件路径
_AGENTS_MD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AGENTS.md")


def _try_update_agents_md(section: str, new_content: str):
    """尝试在 AGENTS.md 的指定段落末尾追加内容"""
    if not section or not new_content:
        return

    try:
        with open(_AGENTS_MD_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # 找到 ## section 段落的末尾（下一个 ## 之前）
        section_header = f"## {section}"
        if section_header not in content:
            logger.warning("AGENTS.md 中未找到段落: %s", section)
            return

        lines = content.split("\n")
        new_lines = []
        in_target = False
        inserted = False

        for i, line in enumerate(lines):
            if line.strip().startswith("## "):
                if in_target and not inserted:
                    # 在目标段落结束前插入新内容
                    new_lines.append(new_content)
                    new_lines.append("")
                    inserted = True
                in_target = line.strip() == section_header

            new_lines.append(line)

        # 如果目标段落是最后一个段落
        if in_target and not inserted:
            new_lines.append(new_content)

        with open(_AGENTS_MD_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        logger.info("AGENTS.md [%s] 段落已自动更新", section)

    except Exception as e:
        logger.error("更新 AGENTS.md 失败: %s", e)


def _try_reflect_and_update(client: OpenAI, messages: list[dict], matched_skills: list[dict],
                            query: str = "", user: str = None, tool_call_count: int = 0):
    """
    反思步骤：分析完成后评估执行质量并自动改进。
    根据分析复杂度决定反思级别：
      - 简单查询（0-1次工具调用）：只做记忆沉淀，跳过反思
      - 深度分析（2+次工具调用）：完整反思（Skill更新 + AGENTS.md更新 + 案例沉淀 + 记忆沉淀）
    """
    is_deep_analysis = tool_call_count >= 2

    # ---- 1. Skill/AGENTS.md 反思（仅深度分析时触发） ----
    if is_deep_analysis:
        logger.info("深度分析（%d次工具调用），执行完整反思", tool_call_count)
        try:
            reflect_messages = messages.copy()
            reflect_messages.append({"role": "user", "content": REFLECTION_PROMPT})

            response = client.chat.completions.create(
                model=LLM_CONFIG["model"],
                messages=reflect_messages,
                temperature=0.3,
                max_tokens=800,
            )
            reflect_text = response.choices[0].message.content or ""

            json_match = re.search(r"\{[\s\S]*\}", reflect_text)
            if not json_match:
                logger.debug("反思未返回有效 JSON")
            else:
                reflection = json.loads(json_match.group())

                # 记录执行问题
                issues = reflection.get("execution_issues", [])
                if issues:
                    logger.info("反思发现执行问题: %s", issues)

                # 更新 Skill
                if reflection.get("should_update") and matched_skills:
                    skill_name = reflection.get("skill_name", "")
                    update_section = reflection.get("update_section", "知识")
                    new_content = reflection.get("new_content", "")
                    improvement_note = reflection.get("improvement_note", "")

                    if skill_name and new_content:
                        from skill_manager import append_improvement_log, update_skill

                        target_skill = None
                        for s in matched_skills:
                            if s["name"] == skill_name:
                                target_skill = s
                                break

                        if target_skill:
                            current = target_skill.get(update_section.lower(), target_skill.get("knowledge", ""))
                            updated = current.rstrip() + "\n" + new_content
                            update_skill(skill_name, update_section, updated)

                            old_version = target_skill.get("version", "1.0")
                            parts = old_version.split(".")
                            new_version = f"{parts[0]}.{int(parts[-1]) + 1}"
                            append_improvement_log(skill_name, new_version, improvement_note)
                            logger.info("Skill [%s] 已自动更新至 v%s: %s", skill_name, new_version, improvement_note)

                # 更新 AGENTS.md
                agents_update = reflection.get("agents_md_update", {})
                if agents_update.get("should_update"):
                    _try_update_agents_md(
                        agents_update.get("section", ""),
                        agents_update.get("new_content", ""),
                    )

                # 沉淀案例
                new_case = reflection.get("new_case", {})
                if new_case.get("should_save") and new_case.get("title") and new_case.get("content"):
                    from knowledge_base import save_case
                    save_case(new_case["title"], new_case["content"])
                    logger.info("已沉淀新分析案例: %s", new_case["title"])

        except Exception as e:
            logger.debug("反思更新失败（不影响主流程）: %s", e)
    else:
        logger.debug("简单查询（%d次工具调用），跳过Skill反思", tool_call_count)

    # ---- 2. 记忆沉淀（有工具调用时才执行，纯问答不沉淀） ----
    if tool_call_count >= 1:
        try:
            memory_messages = messages.copy()
            memory_messages.append({"role": "user", "content": MEMORY_EXTRACT_PROMPT})

            mem_response = client.chat.completions.create(
                model=LLM_CONFIG["model"],
                messages=memory_messages,
                temperature=0.3,
                max_tokens=500,
            )
            mem_text = mem_response.choices[0].message.content or ""
            mem_match = re.search(r"\{[\s\S]*\}", mem_text)
            if mem_match:
                mem_json = json.loads(mem_match.group())
                if save_memory_from_reflection(mem_json, query=query, user=user):
                    logger.info("已沉淀分析记忆: %s/%s", mem_json.get("category"), mem_json.get("subject"))
        except Exception as e:
            logger.debug("记忆沉淀失败（不影响主流程）: %s", e)
    else:
        logger.debug("无工具调用，跳过记忆沉淀")


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

    # 自动检测用户画像信息（从用户输入中识别角色/偏好）
    if user:
        detected = try_detect_profile_from_query(query)
        if detected:
            update_profile(user, **detected)
            logger.info("自动识别用户画像 [%s]: %s", user, detected)
        record_interaction(user, query)

    # 检测追问：如果是追问，给上一轮使用的 Skill 记录 followup
    is_followup = _detect_followup(session_id, query)
    if is_followup:
        last_skills = _session_last_skills.get(session_id, [])
        for sname in last_skills:
            record_skill_usage(sname, "followup")
            # 检查是否需要回退
            rollback_ver = evaluate_and_maybe_rollback(sname)
            if rollback_ver:
                logger.warning("Skill [%s] 因评分过低已自动回退到 %s", sname, rollback_ver)

    # 匹配相关 Skill
    matched_skills = match_skills(query)
    skill_prompt = build_skill_prompt(matched_skills)
    if matched_skills:
        logger.info("匹配到 Skill: %s", [s["name"] for s in matched_skills])
    else:
        # 未匹配到 Skill，记录未覆盖问题
        trigger_category = record_uncovered_query(query)
        if trigger_category:
            # 累积达到阈值，尝试自动生成新 Skill
            logger.info("触发 Skill 自动生成（类别: %s）", trigger_category)
            new_skill_name = generate_skill_from_queries(client, trigger_category)
            if new_skill_name:
                logger.info("新 Skill [%s] 已自动生成，重新匹配", new_skill_name)
                # 重新匹配（新 Skill 可能匹配当前问题）
                matched_skills = match_skills(query)
                skill_prompt = build_skill_prompt(matched_skills)

    # 构建 system prompt = 基础 prompt + 数据上下文 + 用户画像 + 知识上下文 + 匹配的 Skill
    system_prompt = BASE_SYSTEM_PROMPT.format(data_context=_build_all_data_context())

    # 注入用户画像（定制交互风格）
    user_prompt = build_user_prompt(user)
    if user_prompt:
        system_prompt += "\n" + user_prompt

    # 注入知识库上下文（基线标准 + 相关术语/案例）
    knowledge_prompt = build_knowledge_prompt(query)
    if knowledge_prompt:
        system_prompt += "\n" + knowledge_prompt

    # 注入历史分析记忆（闭环跟踪：对比上次分析结论）
    memory_prompt = build_memory_prompt(query)
    if memory_prompt:
        system_prompt += "\n" + memory_prompt

    # 注入匹配的 Skill
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

            # 记录 Skill 使用成功（非追问场景下本轮的 Skill）
            _record_skill_success(session_id, matched_skills)

            # 反思：根据分析深度决定反思级别
            _try_reflect_and_update(client, messages + [{"role": "assistant", "content": answer}], matched_skills,
                                   query=query, user=user, tool_call_count=len(tool_records))

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

    # 记录 Skill 使用成功
    _record_skill_success(session_id, matched_skills)

    # 反思：根据分析深度决定反思级别
    _try_reflect_and_update(client, messages + [{"role": "assistant", "content": answer}], matched_skills,
                           query=query, user=user, tool_call_count=len(tool_records))

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
