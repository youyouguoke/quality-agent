"""
质量管理 AI Agent 系统 - 用户画像管理
根据用户角色和偏好定制交互方式，通过对话自动识别并持续更新画像。

画像以 JSON 文件存储在 user_profiles/ 目录，按 smartmi-ua 用户名命名。

画像字段：
  - role:        角色（quality_engineer/manager/procurement/production/other）
  - department:  部门
  - focus_areas:  关注领域列表
  - detail_level: 偏好详细程度（detailed/summary/auto）
  - common_queries: 常见问题类型统计
  - interaction_count: 累计对话次数
  - last_active: 最后活跃时间
  - notes:       其他备注
"""
import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

PROFILES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_profiles")

# 角色定义：不同角色的交互差异
ROLE_CONFIGS = {
    "quality_engineer": {
        "label": "质量工程师",
        "style": "提供详细的技术分析，包含具体数据、根因推理链和改善措施细节。可以使用专业术语，无需额外解释。",
        "focus": "关注不良根因、物料追溯、工艺改进、供应商管控细节。",
    },
    "manager": {
        "label": "管理层",
        "style": "提供简洁的结论和趋势判断，用表格和图表化描述。重点突出风险和决策建议，避免过多技术细节。",
        "focus": "关注整体趋势、同比环比、风险预警、资源投入产出。",
    },
    "procurement": {
        "label": "采购",
        "style": "围绕供应商维度分析，提供横向对比数据和成本影响评估。",
        "focus": "关注供应商质量排名、来料合格率、退货率、替代供应商建议。",
    },
    "production": {
        "label": "生产/制造",
        "style": "围绕生产过程和工厂维度分析，关注直通率和制程改进。",
        "focus": "关注代工厂质量、制程直通率、产线不良率、工艺参数。",
    },
    "other": {
        "label": "通用用户",
        "style": "用通俗易懂的语言解释分析结果，必要时解释专业术语。",
        "focus": "根据用户问题灵活调整分析侧重点。",
    },
}

# 默认画像
DEFAULT_PROFILE = {
    "role": "other",
    "department": "",
    "focus_areas": [],
    "detail_level": "auto",
    "common_queries": {},
    "interaction_count": 0,
    "last_active": None,
    "notes": "",
}


# ======================== 画像读写 ========================

def _get_profile_path(username: str) -> str:
    return os.path.join(PROFILES_DIR, f"{username}.json")


def get_profile(username: str) -> dict:
    """获取用户画像，不存在则返回默认画像"""
    if not username:
        return DEFAULT_PROFILE.copy()

    filepath = _get_profile_path(username)
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                profile = json.load(f)
            # 补全缺失字段
            for k, v in DEFAULT_PROFILE.items():
                if k not in profile:
                    profile[k] = v
            return profile
        except Exception as e:
            logger.error("读取用户画像失败 [%s]: %s", username, e)

    return DEFAULT_PROFILE.copy()


def save_profile(username: str, profile: dict) -> bool:
    """保存用户画像"""
    if not username:
        return False

    os.makedirs(PROFILES_DIR, exist_ok=True)
    filepath = _get_profile_path(username)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        logger.info("已保存用户画像: %s (角色: %s)", username, profile.get("role"))
        return True
    except Exception as e:
        logger.error("保存用户画像失败 [%s]: %s", username, e)
        return False


def update_profile(username: str, **fields) -> dict:
    """局部更新用户画像字段"""
    profile = get_profile(username)
    profile.update(fields)
    save_profile(username, profile)
    return profile


# ======================== 对话统计更新 ========================

def record_interaction(username: str, query: str):
    """记录一次对话交互，更新统计信息"""
    if not username:
        return

    profile = get_profile(username)
    profile["interaction_count"] = profile.get("interaction_count", 0) + 1
    profile["last_active"] = datetime.now().isoformat()

    # 统计问题类型
    query_types = profile.get("common_queries", {})
    detected_type = _detect_query_type(query)
    if detected_type:
        query_types[detected_type] = query_types.get(detected_type, 0) + 1
        profile["common_queries"] = query_types

    save_profile(username, profile)


def _detect_query_type(query: str) -> Optional[str]:
    """简单检测问题类型"""
    q = query.lower()
    type_keywords = {
        "客退分析": ["客退", "退货", "退货率", "客退分析"],
        "SN溯源": ["sn", "序列号", "溯源"],
        "供应商分析": ["供应商", "iqc", "来料"],
        "SKU分析": ["sku", "产品质量", "型号"],
        "代工厂分析": ["代工厂", "工厂", "产线"],
        "根因分析": ["根因", "根本原因", "为什么"],
        "预警查询": ["预警", "告警", "异常", "巡检"],
    }
    for qtype, keywords in type_keywords.items():
        for kw in keywords:
            if kw in q:
                return qtype
    return "其他"


# ======================== 构建用户画像 Prompt ========================

def build_user_prompt(username: str) -> str:
    """根据用户画像构建 system prompt 片段"""
    if not username:
        return ""

    profile = get_profile(username)
    role = profile.get("role", "other")
    role_config = ROLE_CONFIGS.get(role, ROLE_CONFIGS["other"])

    parts = [f"\n## 当前用户画像\n"]
    parts.append(f"- **用户**: {username}")
    parts.append(f"- **角色**: {role_config['label']}")

    if profile.get("department"):
        parts.append(f"- **部门**: {profile['department']}")

    if profile.get("focus_areas"):
        parts.append(f"- **关注领域**: {', '.join(profile['focus_areas'])}")

    parts.append(f"\n**交互风格要求**: {role_config['style']}")
    parts.append(f"**分析侧重**: {role_config['focus']}")

    detail = profile.get("detail_level", "auto")
    if detail == "detailed":
        parts.append("**详细程度**: 用户偏好详细报告，尽量展示完整数据和分析过程。")
    elif detail == "summary":
        parts.append("**详细程度**: 用户偏好简洁摘要，突出关键结论和行动建议。")

    # 根据历史问题类型推断用户兴趣
    common = profile.get("common_queries", {})
    if common:
        top_types = sorted(common.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = "、".join(f"{t}({c}次)" for t, c in top_types)
        parts.append(f"**历史关注**: {top_str}")

    parts.append("")
    return "\n".join(parts)


# ======================== 对话中自动识别画像 ========================

PROFILE_DETECT_PROMPT = """根据用户的这句话，判断是否透露了职业角色或偏好信息。
如果有，返回 JSON；如果没有，返回 {"detected": false}。

可识别的角色：quality_engineer(质量工程师)、manager(管理层)、procurement(采购)、production(生产制造)

```json
{
    "detected": true/false,
    "role": "角色代码（如果识别到）",
    "department": "部门名称（如果提到）",
    "focus_areas": ["关注领域1", "关注领域2"],
    "detail_level": "detailed/summary（如果用户表达了偏好）"
}
```
只返回 JSON。"""


def try_detect_profile_from_query(query: str) -> Optional[dict]:
    """
    从用户输入中检测角色/偏好关键词（轻量本地检测，不调 LLM）。
    只在明确表达时触发，避免误判。
    """
    q = query.lower()

    detected = {}

    # 角色检测
    role_keywords = {
        "quality_engineer": ["我是质量工程师", "质量工程师", "我是qa", "我做质量"],
        "manager": ["我是经理", "我是总监", "管理层", "我是leader", "我是主管"],
        "procurement": ["我是采购", "我做采购", "采购部"],
        "production": ["我是生产", "产线", "我做制造", "我是工厂"],
    }
    for role, keywords in role_keywords.items():
        for kw in keywords:
            if kw in q:
                detected["role"] = role
                break

    # 偏好检测
    if "简洁" in q or "简要" in q or "概要" in q:
        detected["detail_level"] = "summary"
    elif "详细" in q or "详情" in q or "展开" in q:
        detected["detail_level"] = "detailed"

    # 部门检测
    dept_keywords = ["质量部", "品质部", "采购部", "生产部", "研发部", "工程部", "售后部"]
    for dept in dept_keywords:
        if dept in q:
            detected["department"] = dept
            break

    if detected:
        return detected
    return None
