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
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory")

# 记忆保留时长（默认30天）
MEMORY_RETENTION_DAYS = 30


def _is_expired(memory: dict) -> bool:
    """判断一条记忆是否已过期"""
    time_str = memory.get("time", "")
    if not time_str:
        return True
    try:
        mem_time = datetime.fromisoformat(time_str)
        return datetime.now() - mem_time > timedelta(days=MEMORY_RETENTION_DAYS)
    except (ValueError, TypeError):
        return True


def _cleanup_file(filepath: str) -> int:
    """清理文件中过期的记忆，返回清理的条数"""
    if not os.path.exists(filepath):
        return 0

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        valid = []
        removed = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                mem = json.loads(line)
                if _is_expired(mem):
                    removed += 1
                else:
                    valid.append(line)
            except json.JSONDecodeError:
                removed += 1

        if removed > 0:
            with open(filepath, "w", encoding="utf-8") as f:
                for line in valid:
                    f.write(line + "\n")
            logger.info("清理过期记忆 [%s]: 删除 %d 条，保留 %d 条", filepath, removed, len(valid))

        return removed
    except Exception as e:
        logger.error("清理记忆文件失败 [%s]: %s", filepath, e)
        return 0

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
    保存一条分析记忆。保存时自动清理过期记忆，同类型只保留最新一条。

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
        # 1. 读取现有记忆
        existing = []
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        # 2. 清理过期记忆
        valid = [m for m in existing if not _is_expired(m)]

        # 3. 同类型记忆去重：如果已有同 type 的记忆，替换为最新的
        mem_type = memory.get("type", "")
        if mem_type:
            valid = [m for m in valid if m.get("type") != mem_type]

        # 4. 追加新记忆
        valid.append(memory)

        # 5. 重写文件
        with open(filepath, "w", encoding="utf-8") as f:
            for m in valid:
                f.write(json.dumps(m, ensure_ascii=False, default=str) + "\n")

        logger.info("已保存记忆 [%s/%s]: %s（文件中共 %d 条）", category, subject, mem_type, len(valid))
        return True
    except Exception as e:
        logger.error("保存记忆失败 [%s/%s]: %s", category, subject, e)
        return False


# ======================== 记忆读取 ========================

def load_memories(category: str, subject: str, limit: int = 10) -> list[dict]:
    """
    读取指定主题的历史记忆（最新的在前，自动过滤过期记忆）。
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
                        mem = json.loads(line)
                        if not _is_expired(mem):
                            memories.append(mem)
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error("读取记忆失败 [%s/%s]: %s", category, subject, e)
        return []

    memories.reverse()
    return memories[:limit]


def load_all_memories_in_category(category: str, limit_per_file: int = 3) -> list[dict]:
    """读取某个分类下所有文件的最近记忆（自动过滤过期）"""
    dir_path = os.path.join(MEMORY_DIR, category)
    if not os.path.isdir(dir_path):
        return []

    all_memories = []
    for filename in os.listdir(dir_path):
        if not filename.endswith(".jsonl"):
            continue
        subject = filename.replace(".jsonl", "")
        memories = load_memories(category, subject, limit=limit_per_file)  # 已内置过期过滤
        all_memories.extend(memories)

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
    根据用户问题智能检索相关记忆，支持跨维度关联。

    检索策略：
    1. 识别问题涉及的分类和主题
    2. 加载同主题同分类的记忆（优先级最高）
    3. 跨维度关联：扫描其他分类的记忆，找到 related_entities 中包含当前主题的记忆
    4. 补充同分类其他主题的最新记忆
    """
    categories = _detect_category(query)
    subject = _detect_subject(query)

    memories = []
    seen_ids = set()  # 去重用（time + subject 组合）

    def _add_unique(mem_list: list[dict]):
        for m in mem_list:
            mid = f"{m.get('time', '')}_{m.get('subject', '')}"
            if mid not in seen_ids:
                seen_ids.add(mid)
                memories.append(m)

    # ---- 第1层：同主题同分类（最相关） ----
    if subject:
        for cat in categories:
            _add_unique(load_memories(cat, subject, limit=3))

    # ---- 第2层：跨维度关联（核心新增） ----
    if subject and len(memories) < limit:
        # 扫描所有分类的所有记忆，找 related_entities 中包含当前主题的
        all_categories = ["sku", "supplier", "factory", "root_cause", "general"]
        for cat in all_categories:
            if cat in categories and subject:
                continue  # 已经在第1层查过了
            cross_mems = load_all_memories_in_category(cat, limit_per_file=2)
            for m in cross_mems:
                if len(memories) >= limit:
                    break
                related = m.get("related_entities", {})
                # 检查当前主题是否出现在任何关联实体列表中
                all_related_names = []
                for entity_list in related.values():
                    if isinstance(entity_list, list):
                        all_related_names.extend(entity_list)
                if subject in all_related_names:
                    _add_unique([m])

    # ---- 第3层：同分类其他主题（补充） ----
    if len(memories) < limit:
        for cat in categories:
            all_mems = load_all_memories_in_category(cat, limit_per_file=2)
            _add_unique(all_mems)
            if len(memories) >= limit:
                break

    return memories[:limit]


# ======================== 构建记忆 Prompt ========================

def build_memory_prompt(query: str) -> str:
    """根据用户问题检索相关记忆（含跨维度关联），构建 prompt 片段"""
    memories = retrieve_relevant_memories(query, limit=5)
    if not memories:
        return ""

    subject = _detect_subject(query)
    parts = ["\n## 历史分析记忆\n"]

    for i, mem in enumerate(memories, 1):
        time_str = mem.get("time", "未知")[:10]
        mem_subject = mem.get("subject", "")
        mtype = mem.get("type", "")
        conclusion = mem.get("conclusion", "")
        findings = mem.get("key_findings", [])
        metrics = mem.get("metrics", {})
        related = mem.get("related_entities", {})

        # 标注是同主题记忆还是跨维度关联
        if subject and mem_subject == subject:
            tag = "同主题"
        elif subject and related:
            all_related = []
            for v in related.values():
                if isinstance(v, list):
                    all_related.extend(v)
            if subject in all_related:
                tag = "跨维度关联"
            else:
                tag = "同分类参考"
        else:
            tag = "参考"

        parts.append(f"### 记忆{i}（{tag}）：{mem_subject}（{time_str}，{mtype}）")
        if conclusion:
            parts.append(f"**结论**：{conclusion}")
        if findings:
            parts.append("**关键发现**：")
            for f in findings:
                parts.append(f"- {f}")
        if metrics:
            metrics_str = "、".join(f"{k}: {v}" for k, v in metrics.items())
            parts.append(f"**指标**：{metrics_str}")
        if related:
            related_items = []
            for entity_type, names in related.items():
                if isinstance(names, list) and names:
                    label = {"sku_names": "SKU", "supplier_names": "供应商",
                             "material_names": "物料", "factory_names": "工厂"}.get(entity_type, entity_type)
                    related_items.append(f"{label}: {', '.join(names)}")
            if related_items:
                parts.append(f"**关联实体**：{'；'.join(related_items)}")
        parts.append("")

    parts.append("**请对比历史分析结论**：如果指标有变化，主动说明是改善还是恶化。跨维度关联的记忆可帮助发现不同维度之间的隐藏关系。\n")
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
    "metrics": {"关键指标名": "指标值"},
    "related_entities": {
        "sku_names": ["涉及的SKU名称列表"],
        "supplier_names": ["涉及的供应商名称列表"],
        "material_names": ["涉及的物料名称列表"],
        "factory_names": ["涉及的工厂名称列表"]
    }
}
```
只返回 JSON。related_entities 用于跨维度关联，请尽量填写本次分析涉及的所有实体名称。"""


def save_memory_from_reflection(reflection_json: dict, query: str, user: str = None) -> bool:
    """从 LLM 反思结果中提取并保存记忆（含关联实体）"""
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
        "related_entities": reflection_json.get("related_entities", {}),
        "user": user,
    }

    return save_memory(category, subject, memory)
