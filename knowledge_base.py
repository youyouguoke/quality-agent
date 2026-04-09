"""
质量管理 AI Agent 系统 - 知识库管理
负责质量领域知识的加载、检索和自动沉淀。

知识以 Markdown 文件存储在 knowledge/ 目录中，分三类：
  - 质量基线标准.md  → 各类指标的正常范围、预警线、判断规则
  - 质量专业术语.md  → IQC/PQC/OQC 等术语解释
  - 历史分析案例.md  → 可复用的分析经验和处理方案
"""
import logging
import os
import re
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# 知识库文件目录
KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge")


# ======================== 知识文件加载 ========================

_knowledge_cache: dict[str, str] = {}
_knowledge_loaded: bool = False


def _load_file(filepath: str) -> str:
    """读取单个知识文件"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        logger.error("读取知识文件失败 [%s]: %s", filepath, e)
        return ""


def load_all_knowledge(force_reload: bool = False) -> dict[str, str]:
    """
    加载 knowledge/ 目录下的所有 Markdown 文件。
    返回 {文件名(不含.md): 内容} 的字典。
    """
    global _knowledge_cache, _knowledge_loaded

    if _knowledge_loaded and not force_reload:
        return _knowledge_cache

    knowledge = {}
    if not os.path.isdir(KNOWLEDGE_DIR):
        logger.warning("知识库目录不存在: %s", KNOWLEDGE_DIR)
        _knowledge_cache = {}
        _knowledge_loaded = True
        return knowledge

    for filename in os.listdir(KNOWLEDGE_DIR):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(KNOWLEDGE_DIR, filename)
        content = _load_file(filepath)
        if content:
            name = filename.replace(".md", "")
            knowledge[name] = content
            logger.info("已加载知识: %s (%d 字符)", name, len(content))

    _knowledge_cache = knowledge
    _knowledge_loaded = True
    logger.info("共加载 %d 个知识文件", len(knowledge))
    return knowledge


# ======================== 知识检索 ========================

def get_baselines() -> str:
    """获取质量基线标准"""
    knowledge = load_all_knowledge()
    return knowledge.get("质量基线标准", "")


def get_terminology() -> str:
    """获取质量专业术语"""
    knowledge = load_all_knowledge()
    return knowledge.get("质量专业术语", "")


def get_cases() -> str:
    """获取历史分析案例"""
    knowledge = load_all_knowledge()
    return knowledge.get("历史分析案例", "")


def search_knowledge(query: str) -> list[dict]:
    """
    根据关键词在所有知识文件中检索相关段落。

    Returns:
        [{"source": "文件名", "section": "段落标题", "content": "段落内容", "relevance": 分数}]
    """
    knowledge = load_all_knowledge()
    results = []
    query_lower = query.lower()
    query_keywords = set(re.findall(r"[\w\u4e00-\u9fff]+", query_lower))

    for name, content in knowledge.items():
        # 按 ## 标题分段
        sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

        for section in sections:
            if not section.strip():
                continue

            # 提取段落标题
            title_match = re.match(r"^##\s+(.+)", section)
            title = title_match.group(1).strip() if title_match else ""

            section_lower = section.lower()
            section_keywords = set(re.findall(r"[\w\u4e00-\u9fff]+", section_lower))

            # 计算关键词重合度
            overlap = len(query_keywords & section_keywords)
            if overlap == 0:
                continue

            relevance = overlap / max(len(query_keywords), 1)

            # 关键词直接出现在段落中加分
            for kw in query_keywords:
                if kw in section_lower:
                    relevance += 0.5

            results.append({
                "source": name,
                "section": title,
                "content": section.strip(),
                "relevance": round(relevance, 2),
            })

    # 按相关度排序
    results.sort(key=lambda x: x["relevance"], reverse=True)
    return results[:5]  # 最多返回5个最相关段落


# ======================== 构建知识 Prompt ========================

def build_knowledge_prompt(query: str) -> str:
    """
    根据用户问题构建知识上下文 prompt。
    始终注入基线标准（核心），按需注入相关术语和案例。
    """
    parts = []

    # 始终注入基线标准（是分析的判断依据）
    baselines = get_baselines()
    if baselines:
        parts.append("\n## 质量基线标准（分析时必须参考）\n")
        parts.append(baselines)

    # 检索与问题相关的知识片段
    related = search_knowledge(query)
    if related:
        parts.append("\n## 相关领域知识\n")
        for item in related:
            if item["source"] == "质量基线标准":
                continue  # 已经完整注入，跳过
            parts.append(f"**来源: {item['source']} - {item['section']}**")
            parts.append(item["content"])
            parts.append("")

    if not parts:
        return ""

    return "\n".join(parts)


# ======================== 知识自动沉淀 ========================

def save_case(title: str, content: str) -> bool:
    """
    将新的分析案例追加到历史分析案例文件中。

    Args:
        title: 案例标题（如 "某净化器WiFi模块批次不良"）
        content: 案例内容（包含时间、产品、现象、根因、措施、效果、经验）
    """
    filepath = os.path.join(KNOWLEDGE_DIR, "历史分析案例.md")

    try:
        existing = _load_file(filepath)
        today = date.today().isoformat()

        new_case = f"\n### {title}\n- **记录时间**: {today}\n{content}\n"

        updated = existing.rstrip() + "\n" + new_case

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(updated)

        # 刷新缓存
        load_all_knowledge(force_reload=True)
        logger.info("已沉淀新案例: %s", title)
        return True

    except Exception as e:
        logger.error("保存案例失败: %s", e)
        return False


def update_baseline(sku_category: str, metric: str, value: str) -> bool:
    """
    更新某个 SKU 类别的基线标准。

    Args:
        sku_category: SKU类别（如 "空气净化器"）
        metric: 指标名（如 "正常范围"）
        value: 新值（如 "≤1.8%"）
    """
    filepath = os.path.join(KNOWLEDGE_DIR, "质量基线标准.md")

    try:
        content = _load_file(filepath)
        if not content:
            return False

        # 简单的表格行替换（找到包含 sku_category 的行）
        lines = content.split("\n")
        updated = False
        for i, line in enumerate(lines):
            if sku_category in line and "|" in line:
                # 找到对应行，记录但不自动替换（避免误改）
                logger.info("找到基线行 [%s]: %s", sku_category, line.strip())
                updated = True
                break

        if not updated:
            logger.warning("未找到 SKU 类别 [%s] 的基线记录", sku_category)

        return updated

    except Exception as e:
        logger.error("更新基线失败: %s", e)
        return False
