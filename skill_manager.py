"""
质量管理 AI Agent 系统 - Skill 管理器
负责 Skill 的加载、解析、匹配、自动更新、效果评估和版本回退。

Skill 以 Markdown 文件存储在 skills/ 目录中，每个文件是一个独立技能。
Markdown 格式约定：
  # 标题          → skill name
  ## 元信息        → version, trigger 等元数据
  ## 描述          → 简要说明
  ## 知识          → 领域知识和判断标准
  ## 流程          → 执行步骤
  ## 输出格式       → 报告结构要求
  ## 改进日志       → 版本历史

效果评估文件：skills/_metrics/{skill_name}.json
版本备份目录：skills/_backups/{skill_name}/v{version}.md
"""
import json
import logging
import os
import re
import shutil
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Skill 文件目录
SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")


# ======================== Skill 解析 ========================

def _parse_metadata(text: str) -> dict[str, str]:
    """从 '## 元信息' 段落中解析键值对"""
    meta = {}
    for line in text.strip().split("\n"):
        m = re.match(r"-\s*\*\*(.+?)\*\*\s*[:：]\s*(.+)", line)
        if m:
            meta[m.group(1).strip()] = m.group(2).strip()
    return meta


def _parse_sections(content: str) -> dict[str, str]:
    """将 Markdown 内容按 ## 标题分段"""
    sections = {}
    current_key = None
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def parse_skill(filepath: str) -> Optional[dict]:
    """
    解析单个 Skill Markdown 文件，返回结构化字典。

    返回格式:
    {
        "name": "客退多维度分析报告",
        "filepath": "/path/to/skill.md",
        "version": "1.0",
        "triggers": ["客退分析", "退货分析", ...],
        "description": "...",
        "knowledge": "...",
        "procedure": "...",
        "output_format": "...",
        "improvement_log": "...",
        "raw_content": "完整 Markdown 原文",
    }
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error("读取 Skill 文件失败 [%s]: %s", filepath, e)
        return None

    # 提取标题
    title_match = re.match(r"^#\s+(.+)", content)
    name = title_match.group(1).strip() if title_match else os.path.basename(filepath).replace(".md", "")

    sections = _parse_sections(content)

    # 解析元信息
    meta = _parse_metadata(sections.get("元信息", ""))

    # 解析触发条件
    triggers = []
    trigger_text = meta.get("触发条件", "")
    if trigger_text:
        triggers = [t.strip() for t in re.split(r"[,、，]", trigger_text) if t.strip()]

    return {
        "name": name,
        "filepath": filepath,
        "version": meta.get("版本", "1.0"),
        "triggers": triggers,
        "description": sections.get("描述", ""),
        "knowledge": sections.get("知识", ""),
        "procedure": sections.get("流程", ""),
        "output_format": sections.get("输出格式", ""),
        "improvement_log": sections.get("改进日志", ""),
        "raw_content": content,
    }


# ======================== Skill 加载 ========================

_skills_cache: list[dict] = []
_skills_loaded: bool = False


def load_all_skills(force_reload: bool = False) -> list[dict]:
    """加载 skills/ 目录下的所有 Skill 文件"""
    global _skills_cache, _skills_loaded

    if _skills_loaded and not force_reload:
        return _skills_cache

    skills = []
    if not os.path.isdir(SKILLS_DIR):
        logger.warning("Skills 目录不存在: %s", SKILLS_DIR)
        _skills_cache = []
        _skills_loaded = True
        return skills

    for filename in os.listdir(SKILLS_DIR):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(SKILLS_DIR, filename)
        skill = parse_skill(filepath)
        if skill:
            skills.append(skill)
            logger.info("已加载 Skill: %s (v%s)", skill["name"], skill["version"])

    _skills_cache = skills
    _skills_loaded = True
    logger.info("共加载 %d 个 Skill", len(skills))
    return skills


# ======================== Skill 匹配 ========================

def match_skills(query: str, top_n: int = 3) -> list[dict]:
    """
    根据用户问题匹配最相关的 Skill。
    使用触发条件关键词匹配 + 描述相关度排序。
    """
    skills = load_all_skills()
    if not skills:
        return []

    scored: list[tuple[float, dict]] = []
    query_lower = query.lower()

    for skill in skills:
        score = 0.0

        # 触发条件匹配（权重最高）
        for trigger in skill["triggers"]:
            if trigger.lower() in query_lower:
                score += 10.0
                break  # 命中一个触发词即可

        # 名称匹配
        if skill["name"].lower() in query_lower or query_lower in skill["name"].lower():
            score += 5.0

        # 描述关键词匹配
        desc_words = set(skill["description"])
        query_words = set(query)
        overlap = len(desc_words & query_words)
        if overlap > 0:
            score += min(overlap * 0.5, 3.0)

        if score > 0:
            scored.append((score, skill))

    # 按得分降序排列
    scored.sort(key=lambda x: x[0], reverse=True)
    return [skill for _, skill in scored[:top_n]]


# ======================== 构建 Skill Prompt ========================

def build_skill_prompt(matched_skills: list[dict]) -> str:
    """
    将匹配到的 Skill 组装为 system prompt 片段。
    注入知识、流程和输出格式要求。
    """
    if not matched_skills:
        return ""

    parts = ["\n## 当前任务匹配的专业技能\n"]
    parts.append("以下是与本次问题相关的专业分析技能，请严格按照技能定义的知识、流程和输出格式执行。\n")

    for skill in matched_skills:
        parts.append(f"### 技能：{skill['name']}（v{skill['version']}）")
        parts.append(f"**说明**：{skill['description']}\n")

        if skill["knowledge"]:
            parts.append("**领域知识**：")
            parts.append(skill["knowledge"])
            parts.append("")

        if skill["procedure"]:
            parts.append("**执行流程**：")
            parts.append(skill["procedure"])
            parts.append("")

        if skill["output_format"]:
            parts.append("**输出格式要求**：")
            parts.append(skill["output_format"])
            parts.append("")

    return "\n".join(parts)


# ======================== Skill 自动更新 ========================

def update_skill(skill_name: str, section: str, new_content: str) -> bool:
    """
    更新指定 Skill 的某个段落内容。更新前自动备份当前版本。
    """
    skills = load_all_skills()
    target = None
    for skill in skills:
        if skill["name"] == skill_name:
            target = skill
            break

    if target is None:
        logger.warning("未找到 Skill: %s", skill_name)
        return False

    # 更新前备份当前版本
    current_version = target.get("version", "1.0")
    _backup_skill(skill_name, current_version)

    filepath = target["filepath"]
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        logger.error("读取 Skill 文件失败: %s", e)
        return False

    # 找到对应段落并替换
    section_header = f"## {section}"
    lines = content.split("\n")
    new_lines = []
    in_target_section = False
    replaced = False

    for line in lines:
        if line.startswith("## "):
            if in_target_section:
                # 目标段落结束，插入新内容
                in_target_section = False
                replaced = True
            if line.strip() == section_header:
                new_lines.append(line)
                new_lines.append(new_content)
                new_lines.append("")
                in_target_section = True
                continue
        if not in_target_section:
            new_lines.append(line)

    # 如果目标段落是最后一个段落
    if in_target_section:
        replaced = True

    if not replaced:
        logger.warning("Skill [%s] 中未找到段落: %s", skill_name, section)
        return False

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))
        # 刷新缓存
        load_all_skills(force_reload=True)
        logger.info("已更新 Skill [%s] 的 [%s] 段落", skill_name, section)
        return True
    except Exception as e:
        logger.error("写入 Skill 文件失败: %s", e)
        return False


def append_improvement_log(skill_name: str, version: str, note: str) -> bool:
    """向 Skill 的改进日志追加一条记录，并更新版本号"""
    skills = load_all_skills()
    target = None
    for skill in skills:
        if skill["name"] == skill_name:
            target = skill
            break

    if target is None:
        return False

    filepath = target["filepath"]
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False

    today = date.today().isoformat()
    new_log_entry = f"- v{version} ({today}): {note}"

    # 追加到改进日志末尾
    if "## 改进日志" in content:
        content = content.rstrip() + "\n" + new_log_entry + "\n"
    else:
        content = content.rstrip() + "\n\n## 改进日志\n" + new_log_entry + "\n"

    # 更新版本号
    content = re.sub(
        r"(-\s*\*\*版本\*\*\s*[:：]\s*)[\d.]+",
        rf"\g<1>{version}",
        content,
    )

    # 更新最后更新时间
    content = re.sub(
        r"(-\s*\*\*最后更新\*\*\s*[:：]\s*)[\d-]+",
        rf"\g<1>{today}",
        content,
    )

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        load_all_skills(force_reload=True)
        logger.info("Skill [%s] 已更新至 v%s: %s", skill_name, version, note)
        return True
    except Exception:
        return False


# ======================== 版本备份与回退 ========================

BACKUPS_DIR = os.path.join(SKILLS_DIR, "_backups")


def _backup_skill(skill_name: str, version: str) -> bool:
    """备份当前版本的 Skill 文件"""
    skills = load_all_skills()
    target = None
    for s in skills:
        if s["name"] == skill_name:
            target = s
            break
    if not target:
        return False

    backup_dir = os.path.join(BACKUPS_DIR, _safe_name(skill_name))
    os.makedirs(backup_dir, exist_ok=True)

    backup_path = os.path.join(backup_dir, f"v{version}.md")
    try:
        shutil.copy2(target["filepath"], backup_path)
        logger.info("已备份 Skill [%s] v%s -> %s", skill_name, version, backup_path)
        return True
    except Exception as e:
        logger.error("备份 Skill 失败: %s", e)
        return False


def _safe_name(name: str) -> str:
    """文件名安全化"""
    return re.sub(r'[\\/:*?"<>|]', '_', name).strip()


def list_backups(skill_name: str) -> list[str]:
    """列出某个 Skill 的所有备份版本"""
    backup_dir = os.path.join(BACKUPS_DIR, _safe_name(skill_name))
    if not os.path.isdir(backup_dir):
        return []
    versions = []
    for f in sorted(os.listdir(backup_dir)):
        if f.endswith(".md") and f.startswith("v"):
            versions.append(f.replace(".md", ""))
    return versions


def rollback_skill(skill_name: str, target_version: str = None) -> bool:
    """
    回退 Skill 到指定版本。不指定版本时回退到上一个备份。

    Args:
        skill_name: Skill 名称
        target_version: 目标版本号（如 "v1.0"），不传则回退到最近的备份
    """
    skills = load_all_skills()
    target_skill = None
    for s in skills:
        if s["name"] == skill_name:
            target_skill = s
            break
    if not target_skill:
        logger.warning("回退失败：未找到 Skill [%s]", skill_name)
        return False

    backups = list_backups(skill_name)
    if not backups:
        logger.warning("回退失败：Skill [%s] 没有备份", skill_name)
        return False

    if target_version:
        if target_version not in backups:
            logger.warning("回退失败：Skill [%s] 没有版本 %s 的备份", skill_name, target_version)
            return False
        version = target_version
    else:
        # 回退到倒数第二个版本（最后一个是当前版本的备份）
        version = backups[-2] if len(backups) >= 2 else backups[-1]

    backup_path = os.path.join(BACKUPS_DIR, _safe_name(skill_name), f"{version}.md")
    try:
        shutil.copy2(backup_path, target_skill["filepath"])
        load_all_skills(force_reload=True)
        logger.info("已回退 Skill [%s] 到 %s", skill_name, version)
        return True
    except Exception as e:
        logger.error("回退 Skill 失败: %s", e)
        return False


# ======================== Skill 效果评估 ========================

METRICS_DIR = os.path.join(SKILLS_DIR, "_metrics")


def _get_metrics_path(skill_name: str) -> str:
    os.makedirs(METRICS_DIR, exist_ok=True)
    return os.path.join(METRICS_DIR, f"{_safe_name(skill_name)}.json")


def _load_metrics(skill_name: str) -> dict:
    """加载 Skill 的效果指标"""
    path = _get_metrics_path(skill_name)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "skill_name": skill_name,
        "total_uses": 0,
        "followup_count": 0,       # 用户追问次数（说明分析不够深入）
        "correction_count": 0,     # 用户纠正次数（说明分析有误）
        "success_count": 0,        # 正常完成次数
        "score": 100.0,            # 效果评分（满分100，低于60需回退）
        "version_scores": {},      # 各版本的评分 {"1.0": 95, "1.1": 80}
        "last_used": None,
        "last_evaluated": None,
    }


def _save_metrics(skill_name: str, metrics: dict):
    """保存 Skill 效果指标"""
    path = _get_metrics_path(skill_name)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.error("保存 Skill 指标失败 [%s]: %s", skill_name, e)


def record_skill_usage(skill_name: str, outcome: str, version: str = None):
    """
    记录一次 Skill 使用结果。

    Args:
        skill_name: Skill 名称
        outcome: 使用结果
            - "success": 正常完成，用户未追问
            - "followup": 用户追问了（可能分析不够深入）
            - "correction": 用户纠正了（分析有误）
        version: 当前 Skill 版本
    """
    metrics = _load_metrics(skill_name)
    metrics["total_uses"] += 1
    metrics["last_used"] = datetime.now().isoformat()

    if outcome == "success":
        metrics["success_count"] += 1
    elif outcome == "followup":
        metrics["followup_count"] += 1
    elif outcome == "correction":
        metrics["correction_count"] += 1

    # 重新计算评分
    total = metrics["total_uses"]
    if total > 0:
        success_rate = metrics["success_count"] / total
        followup_penalty = metrics["followup_count"] / total * 20  # 追问扣分
        correction_penalty = metrics["correction_count"] / total * 40  # 纠正扣分更重
        metrics["score"] = round(max(0, min(100, success_rate * 100 - followup_penalty - correction_penalty)), 1)

    # 记录版本评分
    if version:
        metrics["version_scores"][version] = metrics["score"]

    metrics["last_evaluated"] = datetime.now().isoformat()
    _save_metrics(skill_name, metrics)

    logger.info("Skill [%s] 使用记录: %s (评分: %.1f, 总使用: %d)",
                skill_name, outcome, metrics["score"], total)

    return metrics


def evaluate_and_maybe_rollback(skill_name: str) -> Optional[str]:
    """
    评估 Skill 效果，如果评分过低则自动回退到上一个高分版本。

    Returns:
        回退到的版本号，未回退返回 None
    """
    metrics = _load_metrics(skill_name)

    # 至少使用5次才评估（样本太少不可靠）
    if metrics["total_uses"] < 5:
        return None

    current_score = metrics["score"]

    # 评分低于60分触发回退
    if current_score >= 60:
        return None

    logger.warning("Skill [%s] 评分 %.1f 低于60分，尝试回退", skill_name, current_score)

    # 找到评分最高的历史版本
    version_scores = metrics.get("version_scores", {})
    if not version_scores:
        return None

    # 排除当前版本，找历史最高分
    skills = load_all_skills()
    current_version = None
    for s in skills:
        if s["name"] == skill_name:
            current_version = s.get("version", "1.0")
            break

    best_version = None
    best_score = 0
    for ver, score in version_scores.items():
        if ver != current_version and score > best_score:
            best_score = score
            best_version = ver

    if best_version and best_score > current_score:
        # 先备份当前版本
        if current_version:
            _backup_skill(skill_name, current_version)

        # 回退
        if rollback_skill(skill_name, f"v{best_version}"):
            logger.info("Skill [%s] 已自动回退: v%s (%.1f分) -> v%s (%.1f分)",
                        skill_name, current_version, current_score, best_version, best_score)

            # 重置评估计数（给回退版本重新评估的机会）
            metrics["total_uses"] = 0
            metrics["success_count"] = 0
            metrics["followup_count"] = 0
            metrics["correction_count"] = 0
            metrics["score"] = best_score
            _save_metrics(skill_name, metrics)

            return best_version

    return None


def get_all_skill_metrics() -> list[dict]:
    """获取所有 Skill 的效果指标"""
    if not os.path.isdir(METRICS_DIR):
        return []
    result = []
    for f in os.listdir(METRICS_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(METRICS_DIR, f), "r", encoding="utf-8") as fp:
                    result.append(json.load(fp))
            except Exception:
                continue
    return sorted(result, key=lambda m: m.get("score", 0))


# ======================== 未覆盖问题跟踪 + Skill 自动生成 ========================

UNCOVERED_PATH = os.path.join(SKILLS_DIR, "_uncovered.json")

# 同类问题累积几次后触发自动生成
AUTO_GEN_THRESHOLD = 3


def _load_uncovered() -> dict:
    """加载未覆盖问题记录"""
    if os.path.exists(UNCOVERED_PATH):
        try:
            with open(UNCOVERED_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"clusters": {}}


def _save_uncovered(data: dict):
    """保存未覆盖问题记录"""
    os.makedirs(os.path.dirname(UNCOVERED_PATH), exist_ok=True)
    try:
        with open(UNCOVERED_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        logger.error("保存未覆盖问题记录失败: %s", e)


def _classify_query(query: str) -> str:
    """
    对未匹配问题做简单分类，返回类别标签。
    相似问题归为一类，用于判断是否达到自动生成阈值。
    """
    q = query.lower()

    # 预定义的分类关键词（覆盖常见质量分析场景）
    categories = {
        "对比分析": ["对比", "比较", "哪个好", "排名", "排序"],
        "趋势分析": ["趋势", "月度", "季度", "走势", "变化"],
        "成本分析": ["成本", "费用", "损失", "金额"],
        "效率分析": ["效率", "周期", "时长", "耗时", "速度"],
        "预测分析": ["预测", "预估", "预判", "未来", "下个月"],
        "关联分析": ["关联", "相关", "影响", "因素"],
        "异常检测": ["异常", "突变", "偏离", "离群"],
        "改善跟踪": ["改善", "改进", "效果", "验证", "跟踪", "闭环"],
        "报表导出": ["报表", "导出", "汇总", "报告", "周报", "月报"],
        "人员分析": ["人员", "工程师", "负责人", "团队"],
    }

    for cat, keywords in categories.items():
        for kw in keywords:
            if kw in q:
                return cat

    return "其他"


def record_uncovered_query(query: str) -> Optional[str]:
    """
    记录一个未被 Skill 覆盖的问题。
    如果同类问题累积达到阈值，返回类别名（提示需要自动生成）；否则返回 None。
    """
    data = _load_uncovered()
    clusters = data.get("clusters", {})

    category = _classify_query(query)
    if category not in clusters:
        clusters[category] = {"queries": [], "count": 0, "generated": False}

    cluster = clusters[category]

    # 避免完全重复
    if query not in cluster["queries"]:
        cluster["queries"].append(query)
        cluster["count"] += 1

    # 只保留最近 10 条问题样本
    if len(cluster["queries"]) > 10:
        cluster["queries"] = cluster["queries"][-10:]

    data["clusters"] = clusters
    _save_uncovered(data)

    # 检查是否达到阈值且尚未生成
    if cluster["count"] >= AUTO_GEN_THRESHOLD and not cluster["generated"]:
        logger.info("未覆盖问题类别 [%s] 已累积 %d 次，触发 Skill 自动生成",
                    category, cluster["count"])
        return category

    return None


def generate_skill_from_queries(client, category: str) -> Optional[str]:
    """
    让 LLM 根据累积的未覆盖问题自动生成一个新 Skill。

    Args:
        client: OpenAI client 实例
        category: 问题类别名

    Returns:
        生成的 Skill 名称，失败返回 None
    """
    data = _load_uncovered()
    cluster = data.get("clusters", {}).get(category)
    if not cluster:
        return None

    queries = cluster.get("queries", [])
    if not queries:
        return None

    # 获取现有 Skill 列表，避免重复
    existing_skills = load_all_skills()
    existing_names = [s["name"] for s in existing_skills]
    existing_triggers = []
    for s in existing_skills:
        existing_triggers.extend(s.get("triggers", []))

    prompt = f"""你是质量管理 AI Agent 的 Skill 设计师。用户反复问了一类问题，但当前系统没有对应的 Skill 来处理。
请根据这些问题设计一个新的 Skill。

## 用户问题样本（类别：{category}）
{chr(10).join(f'- {q}' for q in queries)}

## 已有的 Skill（不要重复）
{chr(10).join(f'- {n}' for n in existing_names)}

## 已有的触发关键词（不要重复）
{', '.join(existing_triggers[:30])}

## 可用数据表
- sn_quality_data（SN质量数据）
- sn_quality_key_material（SN关键物料）
- supplier_quality_iqc（供应商IQC）
- supplier_quality_iqc_monthly（供应商月度IQC）
- supplier_performance_comparison（供应商对比）
- return_data（客退数据）
- maintain_consume_material（维修消耗物料）

## 可用工具
query_table, aggregate_query, time_range_query, sn_full_trace, supplier_overview, sku_overview, factory_overview, return_overview, root_cause_analysis, comparative_analysis, baseline_compare, search_knowledge

请严格按以下 Markdown 格式输出完整的 Skill 文件内容（不要输出其他内容）：

```markdown
# Skill名称

## 元信息
- **版本**: 1.0
- **创建时间**: {date.today().isoformat()}
- **最后更新**: {date.today().isoformat()}
- **触发条件**: 关键词1、关键词2、关键词3（用于匹配用户问题）

## 描述
一句话说明这个 Skill 的用途。

## 知识
列出该分析场景需要的领域知识和判断标准。

## 流程
列出具体的执行步骤，说明调用哪些工具、怎样组合数据。

## 输出格式
定义报告的输出结构和格式要求。

## 改进日志
- v1.0 ({date.today().isoformat()}): 由系统根据用户需求自动生成
```"""

    try:
        from config import LLM_CONFIG

        response = client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2000,
        )
        skill_content = response.choices[0].message.content or ""

        # 提取 markdown 代码块中的内容（如果有）
        md_match = re.search(r"```markdown\s*\n([\s\S]*?)\n```", skill_content)
        if md_match:
            skill_content = md_match.group(1)

        # 确保以 # 标题开头
        if not skill_content.strip().startswith("#"):
            logger.warning("自动生成的 Skill 格式不正确")
            return None

        # 提取 Skill 名称
        title_match = re.match(r"^#\s+(.+)", skill_content.strip())
        if not title_match:
            return None
        skill_name = title_match.group(1).strip()

        # 检查是否与已有 Skill 重名
        if skill_name in existing_names:
            logger.warning("自动生成的 Skill [%s] 与已有 Skill 重名，跳过", skill_name)
            return None

        # 保存文件
        filename = _safe_name(skill_name) + ".md"
        filepath = os.path.join(SKILLS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(skill_content)

        # 标记已生成
        data["clusters"][category]["generated"] = True
        data["clusters"][category]["generated_skill"] = skill_name
        data["clusters"][category]["generated_time"] = datetime.now().isoformat()
        _save_uncovered(data)

        # 刷新缓存
        load_all_skills(force_reload=True)

        logger.info("已自动生成新 Skill [%s]（基于 %d 条未覆盖问题）", skill_name, len(queries))
        return skill_name

    except Exception as e:
        logger.error("自动生成 Skill 失败: %s", e)
        return None


def get_uncovered_summary() -> dict:
    """获取未覆盖问题的统计摘要"""
    data = _load_uncovered()
    clusters = data.get("clusters", {})
    summary = {
        "total_categories": len(clusters),
        "total_queries": sum(c.get("count", 0) for c in clusters.values()),
        "pending_generation": [],
        "already_generated": [],
    }
    for cat, info in clusters.items():
        entry = {
            "category": cat,
            "count": info.get("count", 0),
            "sample_queries": info.get("queries", [])[:3],
        }
        if info.get("generated"):
            entry["generated_skill"] = info.get("generated_skill")
            summary["already_generated"].append(entry)
        else:
            summary["pending_generation"].append(entry)

    return summary
