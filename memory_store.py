"""
质量管理 AI Agent 系统 - 分析记忆存储
持久化分析结论，支持闭环跟踪和跨 session 知识复用。

记忆按分析维度分文件存储在 memory/ 目录：
  memory/sku/{sku_name}.jsonl          — 按 SKU 维度
  memory/supplier/{supplier_name}.jsonl — 按供应商维度
  memory/factory/{factory_name}.jsonl   — 按代工厂维度
  memory/root_cause/{sku_name}.jsonl    — 根因分析记忆
  memory/general/insights.jsonl         — 通用/跨维度

每条记忆是一行 JSON：
  {
    "time": "2026-04-13T18:00:00",
    "type": "return_analysis",
    "query": "用户原始问题",
    "subject": "米家空气净化器 5 Pro",
    "conclusion": "结构化结论摘要",
    "key_findings": ["发现1", "发现2"],
    "recommendations": ["建议1"],
    "metrics": {"退货率": "2.5%", ...},
    "user": "zhangzhiguang3"
  }
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")

# 记忆分类与用户问题的匹配关系
_CATEGORY_KEYWORDS = {
    "sku": ["客退", "退货", "退货率", "不良", "复测", "处理状况", "受理原因", "sku", "产品",
            "净化器", "加湿器", "扫地机", "风扇", "取暖器", "新风机", "消毒机"],
    "supplier": ["供应商", "iqc", "来料", "进料", "合格率"],
    "factory": ["代工厂", "工厂", "产线", "直通率"],
    "root_cause": ["根因", "根本原因", "为什么", "追溯", "归因"],
    "general": [],  # 兜底
}

# SKU 名称标准化（去除文件名不允许的字符）
def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


# ======================== 记忆写入 ========================

def save_memory(category: str, subject: str, memory: dict) -> bool:
    """
    保存一条分析记忆。

    Args:
        category: 分类（sku/supplier/factory/root_cause/general）
        subject: 主题（SKU名称/供应商名称/工厂名称，general 时用 "insights"）
        memory: 记忆内容字典
    """
    dir_path = os.path.join(MEMORY_DIR, category)
    os.makedirs(dir_path, exist_ok=True)

    filename = _safe_filename(subject) + ".jsonl"
    filepath = os.path.join(dir_path, filename)

    # 补充时间戳
    if "time" not in memory:
        memory["time"] = datetime.now().isoformat()

    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(memory, ensure_ascii=False, default=str) + "\n")
        logger.info("已保存记忆 [%s/%s]: %s", category, subject, memory.get("type", ""))
        return True
    except Exception as e:
        logger.error("保存记忆失败 [%s/%s]: %s", category, subject, e)
        return False


# ======================== 记忆读取 ========================

def load_memories(category: str, subject: str, limit: int = 10) -> list[dict]:
    """
    读取指定主题的历史记忆（最新的在前）。

    Args:
        category: 分类
        subject: 主题
        limit: 最多返回条数
    """
    filename = _safe_filename(subject) + ".jsonl"
    filepath = os.path.join(MEMORY_DIR, category, filename)

    if not os.path.exists(filepath):
        return []

    memories = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        memories.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error("读取记忆失败 [%s/%s]: %s", category, subject, e)
        return []

    # 最新的在前
    memories.reverse()
    return memories[:limit]


def load_all_memories_in_category(category: str, limit_per_file: int = 3) -> list[dict]:
    """读取某个分类下所有文件的最近记忆"""
    dir_path = os.path.join(MEMORY_DIR, category)
    if not os.path.isdir(dir_path):
        return []

    all_memories = []
    for filename in os.listdir(dir_path):
        if not filename.endswith(".jsonl"):
            continue
        subject = filename.replace(".jsonl", "")
        memories = load_memories(category, subject, limit=limit_per_file)
        all_memories.extend(memories)

    # 按时间排序（最新在前）
    all_memories.sort(key=lambda m: m.get("time", ""), reverse=True)
    return all_memories


# ======================== 智能检索：根据用户问题找相关记忆 ========================

def _detect_category(query: str) -> list[str]:
    """根据用户问题判断应该读取哪些记忆分类"""
    q = query.lower()
    matched = []

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if category == "general":
            continue
        for kw in keywords:
            if kw in q:
                matched.append(category)
                break

    if not matched:
        matched.append("general")

    return matched


def _detect_subject(query: str) -> Optional[str]:
    """从用户问题中提取主题（SKU名称/供应商名称等）"""
    # SKU 名称映射（与 AGENTS.md 中的映射一致）
    sku_map = {
        "全效ultra增强": "米家全效空气净化器 Ultra 增强版",
        "ultra增强": "米家全效空气净化器 Ultra 增强版",
        "全效ultra": "米家全效空气净化器 Ultra",
        "ultra": "米家全效空气净化器 Ultra",
        "全效": "米家全效空气净化器",
        "宠物": "米家宠物空气净化器",
        "消毒机": "米家牌Y-600型过滤式空气消毒机",
        "y-600": "米家牌Y-600型过滤式空气消毒机",
        "4lite": "米家空气净化器 4 Lite",
        "4 lite": "米家空气净化器 4 Lite",
        "5pro": "米家空气净化器 5 Pro",
        "5 pro": "米家空气净化器 5 Pro",
        "5s": "米家空气净化器 5S",
        "6pro": "米家空气净化器 6 Pro",
        "6 pro": "米家空气净化器 6 Pro",
        "6双芯": "米家空气净化器 6 双芯除醛",
        "6除醛": "米家空气净化器 6 双芯除醛",
        "净化器5": "米家空气净化器 5",
    }

    q = query.lower().replace(" ", "")
    # 按长度降序匹配，避免"5"先于"5pro"匹配
    for short, full in sorted(sku_map.items(), key=lambda x: len(x[0]), reverse=True):
        if short.replace(" ", "") in q:
            return full

    return None


def retrieve_relevant_memories(query: str, limit: int = 5) -> list[dict]:
    """
    根据用户问题智能检索相关记忆。

    检索策略：
    1. 识别问题涉及的分类（sku/supplier/factory/root_cause）
    2. 从问题中提取主题（SKU名/供应商名等）
    3. 优先返回同主题的记忆，再补充同分类的其他记忆
    """
    categories = _detect_category(query)
    subject = _detect_subject(query)

    memories = []

    # 优先加载同主题的记忆
    if subject:
        for cat in categories:
            mems = load_memories(cat, subject, limit=limit)
            memories.extend(mems)

    # 如果同主题记忆不够，补充同分类下其他主题的最新记忆
    if len(memories) < limit:
        for cat in categories:
            all_mems = load_all_memories_in_category(cat, limit_per_file=2)
            for m in all_mems:
                if m not in memories:
                    memories.append(m)
                    if len(memories) >= limit:
                        break

    return memories[:limit]


# ======================== 构建记忆 Prompt ========================

def build_memory_prompt(query: str) -> str:
    """根据用户问题检索相关记忆，构建 prompt 片段"""
    memories = retrieve_relevant_memories(query, limit=5)
    if not memories:
        return ""

    parts = ["\n## 历史分析记忆（上次分析的结论，供参考对比）\n"]

    for i, mem in enumerate(memories, 1):
        time_str = mem.get("time", "未知")[:10]
        subject = mem.get("subject", "")
        mtype = mem.get("type", "")
        conclusion = mem.get("conclusion", "")
        findings = mem.get("key_findings", [])
        metrics = mem.get("metrics", {})

        parts.append(f"### 记忆{i}：{subject}（{time_str}，{mtype}）")
        if conclusion:
            parts.append(f"**结论**：{conclusion}")
        if findings:
            parts.append("**关键发现**：")
            for f in findings:
                parts.append(f"- {f}")
        if metrics:
            metrics_str = "、".join(f"{k}: {v}" for k, v in metrics.items())
            parts.append(f"**指标**：{metrics_str}")
        parts.append("")

    parts.append("**请对比上次分析结论**：如果指标有变化，主动说明是改善还是恶化。\n")
    return "\n".join(parts)


# ======================== 从 LLM 反思结果中提取并保存记忆 ========================

MEMORY_EXTRACT_PROMPT = """请从本次分析中提取可持久化的结论摘要，以 JSON 格式返回。
如果本次分析没有值得记忆的结论（比如只是简单查询），返回 {"should_save": false}。

```json
{
    "should_save": true/false,
    "category": "sku/supplier/factory/root_cause/general",
    "subject": "分析主题（如SKU名称、供应商名称）",
    "type": "分析类型（如 return_analysis/supplier_analysis/root_cause）",
    "conclusion": "一句话结论摘要",
    "key_findings": ["关键发现1", "关键发现2"],
    "recommendations": ["改善建议1"],
    "metrics": {"关键指标名": "指标值"}
}
```
只返回 JSON。"""


def save_memory_from_reflection(reflection_json: dict, query: str, user: str = None) -> bool:
    """从 LLM 反思结果中提取并保存记忆"""
    if not reflection_json.get("should_save"):
        return False

    category = reflection_json.get("category", "general")
    subject = reflection_json.get("subject", "unknown")

    memory = {
        "time": datetime.now().isoformat(),
        "type": reflection_json.get("type", "analysis"),
        "query": query,
        "subject": subject,
        "conclusion": reflection_json.get("conclusion", ""),
        "key_findings": reflection_json.get("key_findings", []),
        "recommendations": reflection_json.get("recommendations", []),
        "metrics": reflection_json.get("metrics", {}),
        "user": user,
    }

    return save_memory(category, subject, memory)
