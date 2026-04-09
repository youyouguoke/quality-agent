"""
质量管理 AI Agent 系统 - Skill 管理器
负责 Skill 的加载、解析、匹配和自动更新。

Skill 以 Markdown 文件存储在 skills/ 目录中，每个文件是一个独立技能。
Markdown 格式约定：
  # 标题          → skill name
  ## 元信息        → version, trigger 等元数据
  ## 描述          → 简要说明
  ## 知识          → 领域知识和判断标准
  ## 流程          → 执行步骤
  ## 输出格式       → 报告结构要求
  ## 改进日志       → 版本历史
"""
import logging
import os
import re
from datetime import date
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
    更新指定 Skill 的某个段落内容。

    Args:
        skill_name: Skill 名称
        section: 要更新的段落标题（如 "知识"、"流程"、"改进日志"）
        new_content: 新内容
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
