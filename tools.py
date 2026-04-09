"""
质量管理 AI Agent 系统 - 工具层
定义所有供 Agent 通过 Function Calling 调用的工具。
包括：数据查询工具、统计分析工具、元数据工具。
每个工具包含 OpenAI Function Calling 格式的 schema 和执行函数。
"""
import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from database import (
    get_all_table_info,
    get_table_info,
    get_table_row_count,
    query_table,
    query_table_aggregate,
    query_table_like,
    query_table_time_range,
)

logger = logging.getLogger(__name__)


# ======================== JSON 序列化辅助 ========================

def _serialize(obj: Any) -> Any:
    """处理 MySQL 返回中不可直接 JSON 序列化的类型"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    return obj


def _serialize_rows(rows: list[dict]) -> list[dict]:
    """序列化查询结果中的所有值"""
    return [
        {k: _serialize(v) for k, v in row.items()}
        for row in rows
    ]


# ======================== 工具执行函数 ========================

def tool_query_table(table_key: str, columns: list[str] | None = None,
                     where: dict | None = None, order_by: str | None = None,
                     limit: int = 0) -> str:
    """查询质量数据表"""
    try:
        rows = query_table(table_key, columns=columns, where=where,
                           order_by=order_by, limit=limit)
        rows = _serialize_rows(rows)
        return json.dumps({"count": len(rows), "data": rows}, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_query_table 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_search_table(table_key: str, column: str, keyword: str,
                      limit: int = 0) -> str:
    """模糊搜索质量数据表"""
    try:
        rows = query_table_like(table_key, column, keyword, limit=limit)
        rows = _serialize_rows(rows)
        return json.dumps({"count": len(rows), "data": rows}, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_search_table 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_aggregate_query(table_key: str, group_by: str, agg_column: str,
                         agg_func: str = "AVG", where: dict | None = None,
                         limit: int = 0) -> str:
    """聚合统计查询"""
    try:
        rows = query_table_aggregate(table_key, group_by=group_by,
                                     agg_column=agg_column, agg_func=agg_func,
                                     where=where, limit=limit)
        rows = _serialize_rows(rows)
        return json.dumps({"count": len(rows), "data": rows}, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_aggregate_query 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_time_range_query(table_key: str, time_column: str, start: str,
                          end: str, columns: list[str] | None = None,
                          where: dict | None = None, limit: int = 0) -> str:
    """时间范围查询"""
    try:
        rows = query_table_time_range(table_key, time_column=time_column,
                                      start=start, end=end, columns=columns,
                                      where=where, limit=limit)
        rows = _serialize_rows(rows)
        return json.dumps({"count": len(rows), "data": rows}, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_time_range_query 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_get_table_info(table_key: str) -> str:
    """获取指定数据表的元信息"""
    try:
        info = get_table_info(table_key)
        return json.dumps(info, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_list_all_tables() -> str:
    """列出全部质量数据表及其说明"""
    try:
        infos = get_all_table_info()
        return json.dumps(infos, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_get_table_count(table_key: str) -> str:
    """获取表行数"""
    try:
        count = get_table_row_count(table_key)
        return json.dumps({"table": table_key, "row_count": count}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_sn_full_trace(sn: str) -> str:
    """
    SN全链路溯源：一次性查询SN的质量数据 + 关键物料数据。
    这是一个组合工具，避免Agent多次调用。
    """
    result = {}
    try:
        # 查询SN质量数据
        quality = query_table("sn_quality_data", where={"sn_no": sn})
        result["quality_data"] = _serialize_rows(quality)

        # 查询SN关键物料
        materials = query_table("sn_quality_key_material", where={"sn_no": sn})
        result["key_materials"] = _serialize_rows(materials)

        result["sn"] = sn
        result["has_data"] = bool(quality)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_sn_full_trace 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_supplier_overview(supplier: str) -> str:
    """
    供应商质量概览：一次性查询供应商的IQC数据 + 月度趋势 + 横向对比。
    """
    result = {}
    try:
        iqc = query_table("supplier_quality_iqc", where={"supplier_name": supplier})
        result["iqc_data"] = _serialize_rows(iqc)

        monthly = query_table("supplier_quality_iqc_monthly", where={"supplier_name": supplier},
                              order_by="ic_month")
        result["monthly_trend"] = _serialize_rows(monthly)

        comparison = query_table("supplier_performance_comparison",
                                 where={"supplier_name": supplier})
        result["performance_comparison"] = _serialize_rows(comparison)

        result["supplier"] = supplier
        result["has_data"] = bool(iqc)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_supplier_overview 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_factory_overview(factory: str) -> str:
    """
    代工厂质量概览：一次性查询代工厂的整体质量数据 + 月度趋势。
    """
    result = {"factory": factory}
    try:
        quality = query_table("factory_quality", where={"production_factory": factory})
        result["quality_data"] = _serialize_rows(quality)
    except Exception as e:
        result["quality_data_error"] = str(e)

    try:
        monthly = query_table("factory_quality_monthly", where={"production_factory": factory},
                              order_by="month")
        result["monthly_trend"] = _serialize_rows(monthly)
    except Exception as e:
        result["monthly_trend_error"] = str(e)

    result["has_data"] = bool(result.get("quality_data") or result.get("monthly_trend"))
    return json.dumps(result, ensure_ascii=False)


def tool_sku_overview(sku_name: str) -> str:
    """
    SKU质量概览：一次性查询SKU的整体质量数据 + 月度趋势。
    """
    result = {"sku_name": sku_name}
    try:
        quality = query_table("sku_quality", where={"sku_name": sku_name})
        result["quality_data"] = _serialize_rows(quality)
    except Exception as e:
        result["quality_data_error"] = str(e)

    try:
        monthly = query_table("sku_quality_monthly", where={"sku_name": sku_name},
                              order_by="month")
        result["monthly_trend"] = _serialize_rows(monthly)
    except Exception as e:
        result["monthly_trend_error"] = str(e)

    result["has_data"] = bool(result.get("quality_data") or result.get("monthly_trend"))
    return json.dumps(result, ensure_ascii=False)


def tool_return_overview(sku_name: str = None, factory: str = None, _user: str = None) -> str:
    """
    客退分析报告：按7个维度生成结构化分析数据。
    通过 MCP 工具获取原始数据，本地完成数据加工。

    MCP 工具映射：
    1. get_return_overview        -> 整体概况
    2. get_accept_reason_analysis -> 受理原因分析（四分类归类）
    3. get_retest_result_analysis -> 复测结果分析（TOP5）
    4. get_defect_cause_analysis  -> 不良原因分析（多值拆分 TOP5）
    5. get_defect_material_analysis -> 不良物料分析（多值拆分 TOP5）
    6. get_responsibility_analysis -> 责任归属分析（多值拆分 TOP10）
    7. get_state_analysis         -> 处理状况分析
    """
    # from database import execute_query        # 已废弃：不再使用本地 SQL
    from mcp_client import call_tool as mcp_call

    result = {}

    # 构建 MCP 参数
    mcp_args = {}
    if sku_name:
        mcp_args["sku_name"] = sku_name
    if factory:
        mcp_args["production_factory"] = factory

    # 权限错误：记录哪些维度无权限，但不终止整个函数
    _NO_PERMISSION = "无权限，该维度数据不可用"

    def _try_mcp(tool_name: str, args: dict = None) -> tuple[dict | list | None, bool]:
        """
        尝试调用 MCP 工具。
        返回 (data, is_permission_error):
          - 成功: (data, False)
          - 权限不足: (None, True)
          - 其他错误: (None, False)
        """
        try:
            data = mcp_call(tool_name, args or mcp_args, user=_user)
            if isinstance(data, dict) and "error" in data:
                error_msg = str(data["error"])
                logger.warning("MCP [%s] 返回错误: %s", tool_name, error_msg)
                if "权限" in error_msg:
                    return None, True
                return None, False
            return data, False
        except Exception as e:
            logger.warning("MCP [%s] 调用异常: %s", tool_name, e)
        return None, False

    # ========== 1. 整体概况 ==========
    try:
        mcp_data, perm_denied = _try_mcp("get_return_overview")
        if perm_denied:
            result["overview_error"] = _NO_PERMISSION
        elif mcp_data is not None:
            # MCP 返回格式同原 SQL：[{total_returns, sku_names, ...}] 或 {total_returns, ...}
            o = mcp_data[0] if isinstance(mcp_data, list) and mcp_data else mcp_data
            if isinstance(o, dict):
                total = o.get("total_returns") or 0
                retest_done = o.get("retest_done_count") or 0
                repair_done = o.get("repair_done_count") or 0
                result["overview"] = {
                    "total_returns": total,
                    "sku_names": o.get("sku_names"),
                    "production_factories": o.get("production_factories"),
                    "return_factories": o.get("return_factories"),
                    "retest_done_count": retest_done,
                    "retest_completion_rate": round(retest_done / total * 100, 2) if total else 0,
                    "repair_done_count": repair_done,
                    "repair_completion_rate": round(repair_done / total * 100, 2) if total else 0,
                }
        if "overview" not in result and "overview_error" not in result:
            result["overview_error"] = "MCP get_return_overview 未返回有效数据"
    except Exception as e:
        result["overview_error"] = str(e)

    # ========== 2. 受理原因分析（四分类） ==========
    try:
        accept_rows, perm_denied = _try_mcp("get_accept_reason_analysis")
        if perm_denied:
            result["accept_reason_error"] = _NO_PERMISSION
        elif accept_rows is not None:
            # MCP 返回格式同原 SQL：[{accept_reason: '...', cnt: N}, ...]
            if isinstance(accept_rows, dict):
                accept_rows = [accept_rows]
            quality_reasons = {'平台商-质量', '三包期内换货', '产品质量问题', '维修', '多维换货', '开箱损', '平台商-质量换货'}
            seven_no_reasons = {'7天无理由', '平台商-七无'}
            paid_reasons = {'平台商-付费换新'}
            accept_categories = {"质量": 0, "7无": 0, "付费换新": 0, "其他": 0}
            accept_detail = {"质量": {}, "7无": {}, "付费换新": {}, "其他": {}}
            for row in accept_rows:
                reason = row.get("accept_reason") or "未知"
                cnt = row.get("cnt", 0)
                if reason in quality_reasons:
                    cat = "质量"
                elif reason in seven_no_reasons:
                    cat = "7无"
                elif reason in paid_reasons:
                    cat = "付费换新"
                else:
                    cat = "其他"
                accept_categories[cat] += cnt
                accept_detail[cat][reason] = cnt
            result["accept_reason_analysis"] = {"categories": accept_categories, "detail": accept_detail}
        elif "accept_reason_error" not in result:
            result["accept_reason_error"] = "MCP get_accept_reason_analysis 未返回有效数据"
    except Exception as e:
        result["accept_reason_error"] = str(e)

    # ========== 3. 复测结果分析（仅有复测结果的数据，TOP5） ==========
    try:
        retest_rows, perm_denied = _try_mcp("get_retest_result_analysis")
        if perm_denied:
            result["retest_result_error"] = _NO_PERMISSION
        elif retest_rows is not None:
            # MCP 返回格式同原 SQL：[{retest_result: '...', cnt: N}, ...]
            if isinstance(retest_rows, dict):
                retest_rows = [retest_rows]
            retest_total = sum(r.get("cnt", 0) for r in retest_rows)
            sorted_retest = retest_rows[:5]
            other_retest = sum(r.get("cnt", 0) for r in retest_rows[5:])
            retest_list = [{"retest_result": r.get("retest_result"), "count": r.get("cnt", 0)} for r in sorted_retest]
            if other_retest > 0:
                retest_list.append({"retest_result": "其他", "count": other_retest})
            result["retest_result_analysis"] = {"total_with_result": retest_total, "top5": retest_list}
        elif "retest_result_error" not in result:
            result["retest_result_error"] = "MCP get_retest_result_analysis 未返回有效数据"
    except Exception as e:
        result["retest_result_error"] = str(e)

    # ========== 4. 不良原因分析（仅有复测结果的数据，多值拆分，TOP5） ==========
    try:
        defect_rows, perm_denied = _try_mcp("get_defect_cause_analysis")
        if perm_denied:
            result["defect_cause_error"] = _NO_PERMISSION
        elif defect_rows is not None:
            # MCP 返回格式同原 SQL：[{defect_cause: '...'}, ...]
            if isinstance(defect_rows, dict):
                defect_rows = [defect_rows]
            cause_counter: dict[str, int] = {}
            for row in defect_rows:
                val = row.get("defect_cause")
                if not val:
                    continue
                for item in str(val).split(","):
                    item = item.strip()
                    if item:
                        cause_counter[item] = cause_counter.get(item, 0) + 1
            sorted_causes = sorted(cause_counter.items(), key=lambda x: x[1], reverse=True)
            top5_causes = sorted_causes[:5]
            other_cause_count = sum(c for _, c in sorted_causes[5:])
            result["defect_cause_analysis"] = {
                "top5": [{"defect_cause": k, "count": v} for k, v in top5_causes],
                "other_count": other_cause_count, "total_distinct": len(cause_counter),
            }
        elif "defect_cause_error" not in result:
            result["defect_cause_error"] = "MCP get_defect_cause_analysis 未返回有效数据"
    except Exception as e:
        result["defect_cause_error"] = str(e)

    # ========== 5. 不良物料分析（仅有复测结果的数据，多值拆分，TOP5） ==========
    try:
        material_rows, perm_denied = _try_mcp("get_defect_material_analysis")
        if perm_denied:
            result["defect_material_error"] = _NO_PERMISSION
        elif material_rows is not None:
            # MCP 返回格式同原 SQL：[{defect_material: '...'}, ...]
            if isinstance(material_rows, dict):
                material_rows = [material_rows]
            material_counter: dict[str, int] = {}
            for row in material_rows:
                val = row.get("defect_material")
                if not val:
                    continue
                for item in str(val).split(","):
                    item = item.strip()
                    if item:
                        material_counter[item] = material_counter.get(item, 0) + 1
            sorted_materials = sorted(material_counter.items(), key=lambda x: x[1], reverse=True)
            top5_materials = sorted_materials[:5]
            other_material_count = sum(c for _, c in sorted_materials[5:])
            result["defect_material_analysis"] = {
                "top5": [{"defect_material": k, "count": v} for k, v in top5_materials],
                "other_count": other_material_count, "total_distinct": len(material_counter),
            }
        elif "defect_material_error" not in result:
            result["defect_material_error"] = "MCP get_defect_material_analysis 未返回有效数据"
    except Exception as e:
        result["defect_material_error"] = str(e)

    # ========== 6. 责任归属分析（仅有复测结果的数据，多值拆分，TOP10） ==========
    try:
        resp_rows, perm_denied = _try_mcp("get_responsibility_analysis")
        if perm_denied:
            result["responsibility_error"] = _NO_PERMISSION
        elif resp_rows is not None:
            # MCP 返回格式同原 SQL：[{responsibility_owner: '...'}, ...]
            if isinstance(resp_rows, dict):
                resp_rows = [resp_rows]
            resp_counter: dict[str, int] = {}
            for row in resp_rows:
                val = row.get("responsibility_owner")
                if not val:
                    resp_counter["未填写"] = resp_counter.get("未填写", 0) + 1
                    continue
                for item in str(val).split(","):
                    item = item.strip()
                    if item:
                        resp_counter[item] = resp_counter.get(item, 0) + 1
            sorted_resp = sorted(resp_counter.items(), key=lambda x: x[1], reverse=True)
            top10_resp = sorted_resp[:10]
            other_resp_count = sum(c for _, c in sorted_resp[10:])
            result["responsibility_analysis"] = {
                "top10": [{"responsibility_owner": k, "count": v} for k, v in top10_resp],
                "other_count": other_resp_count, "total_distinct": len(resp_counter),
            }
        elif "responsibility_error" not in result:
            result["responsibility_error"] = "MCP get_responsibility_analysis 未返回有效数据"
    except Exception as e:
        result["responsibility_error"] = str(e)

    # ========== 7. 处理状况分析 ==========
    try:
        state_rows, perm_denied = _try_mcp("get_state_analysis")
        if perm_denied:
            result["state_error"] = _NO_PERMISSION
        elif state_rows is not None:
            # MCP 返回格式同原 SQL：[{state: '...', cnt: N}, ...]
            if isinstance(state_rows, dict):
                state_rows = [state_rows]
            result["state_analysis"] = [
                {"state": r.get("state") or "未知", "count": r.get("cnt", 0)} for r in state_rows
            ]
        elif "state_error" not in result:
            result["state_error"] = "MCP get_state_analysis 未返回有效数据"
    except Exception as e:
        result["state_error"] = str(e)

    result["filter"] = {"sku_name": sku_name, "factory": factory}
    result["has_data"] = bool(result.get("overview", {}).get("total_returns"))

    # 标记哪些维度因权限不足而缺失，告知 LLM 不要用其他工具补查
    no_perm_fields = [k for k, v in result.items() if v == _NO_PERMISSION]
    if no_perm_fields:
        result["permission_note"] = (
            f"以下维度因当前用户无权限而不可用: {no_perm_fields}。"
            "请勿使用其他工具（如query_table、aggregate_query）查询这些数据。"
        )

    return json.dumps(result, ensure_ascii=False, default=str)


# ======================== 基线对比工具 ========================

def tool_baseline_compare(indicator: str, actual_value: float,
                          sku_category: str = None,
                          compare_type: str = "退货率") -> str:
    """
    将实际质量指标与知识库中的基线标准进行对比，返回判定结果。

    Args:
        indicator: 指标名称（如 "退货率", "IQC抽检不合格次数", "直通率"）
        actual_value: 实际数值（百分比形式，如 2.5 表示 2.5%）
        sku_category: SKU类别（如 "空气净化器"），退货率对比时需要
        compare_type: 对比类型，"退货率"/"供应商IQC"/"代工厂"
    """
    try:
        result = {
            "indicator": indicator,
            "actual_value": actual_value,
            "compare_type": compare_type,
        }

        if compare_type == "退货率":
            # SKU 退货率基线
            baselines = {
                "空气净化器": {"normal": 2.0, "warning": 2.0, "critical": 4.0},
                "新风机":     {"normal": 1.5, "warning": 1.5, "critical": 3.0},
                "加湿器":     {"normal": 2.5, "warning": 2.5, "critical": 5.0},
                "扫地机器人": {"normal": 3.0, "warning": 3.0, "critical": 5.0},
                "风扇":       {"normal": 1.0, "warning": 1.0, "critical": 2.0},
                "取暖器":     {"normal": 1.5, "warning": 1.5, "critical": 3.0},
            }
            bl = baselines.get(sku_category, {"normal": 2.0, "warning": 2.0, "critical": 4.0})
            result["sku_category"] = sku_category or "默认"
            result["baseline"] = bl

            if actual_value <= bl["normal"]:
                result["level"] = "正常"
                result["assessment"] = f"退货率 {actual_value}% 在正常范围内（≤{bl['normal']}%）"
            elif actual_value <= bl["critical"]:
                result["level"] = "预警"
                result["assessment"] = f"退货率 {actual_value}% 超过预警线（>{bl['warning']}%），需关注"
            else:
                result["level"] = "严重"
                result["assessment"] = f"退货率 {actual_value}% 超过严重线（>{bl['critical']}%），需立即处理"

        elif compare_type == "供应商IQC":
            # actual_value 为月度IQC抽检不合格次数
            unqualified = int(actual_value)
            if unqualified <= 2:
                result["level"] = "正常"
                result["assessment"] = f"月度IQC抽检不合格 {unqualified} 次，在正常范围内（≤2次）"
            elif unqualified <= 3:
                result["level"] = "预警"
                result["assessment"] = f"月度IQC抽检不合格 {unqualified} 次，超过预警阈值（>2次），需关注"
            else:
                result["level"] = "严重"
                result["assessment"] = f"月度IQC抽检不合格 {unqualified} 次，超过严重阈值（>3次），需立即改善"

        elif compare_type == "代工厂":
            if actual_value >= 98:
                result["level"] = "优秀"
                result["assessment"] = f"{indicator} {actual_value}% 达到优秀水平"
            elif actual_value >= 95:
                result["level"] = "合格"
                result["assessment"] = f"{indicator} {actual_value}% 达到合格水平"
            elif actual_value >= 90:
                result["level"] = "预警"
                result["assessment"] = f"{indicator} {actual_value}% 处于预警区间，需关注"
            else:
                result["level"] = "不合格"
                result["assessment"] = f"{indicator} {actual_value}% 低于合格线，需立即改善"

        else:
            result["level"] = "未知"
            result["assessment"] = f"不支持的对比类型: {compare_type}"

        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error("tool_baseline_compare 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_search_knowledge(query: str) -> str:
    """
    在质量知识库中检索相关知识，包括基线标准、专业术语、历史案例。
    """
    try:
        from knowledge_base import search_knowledge
        results = search_knowledge(query)
        if not results:
            return json.dumps({"message": "未找到相关知识", "results": []}, ensure_ascii=False)
        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_search_knowledge 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ======================== 根因推理链工具 ========================

def tool_root_cause_analysis(sku_name: str = None, defect_material: str = None,
                             defect_cause: str = None, limit: int = 50) -> str:
    """
    根因推理链分析：跨表关联客退数据、SN物料、供应商质量，构建完整证据链。

    从客退现象出发，自动完成：
    1. 筛选相关客退SN（按SKU/不良物料/不良原因过滤）
    2. 追溯这些SN的关键物料和供应商
    3. 统计不良物料→供应商的集中度
    4. 查询嫌疑供应商的IQC质量数据
    5. 统计维修实际更换的物料
    """
    result = {}

    try:
        # ====== 1. 从 return_data 获取相关客退SN ======
        where = {}
        if sku_name:
            where["sku_name"] = sku_name
        # 只取有复测结果的记录（有实际不良判定）
        return_rows = query_table(
            "return_data",
            columns=["sn_no", "sku_name", "production_factory", "defect_cause",
                     "defect_material", "defect_material_batch", "defect_material_supplier",
                     "retest_result", "responsibility_owner", "state"],
            where=where,
            limit=limit,
        )
        return_rows = _serialize_rows(return_rows)

        # 如果指定了不良物料或不良原因，做二次过滤
        if defect_material:
            return_rows = [r for r in return_rows
                          if r.get("defect_material") and defect_material in str(r["defect_material"])]
        if defect_cause:
            return_rows = [r for r in return_rows
                          if r.get("defect_cause") and defect_cause in str(r["defect_cause"])]

        result["return_count"] = len(return_rows)
        result["filter"] = {"sku_name": sku_name, "defect_material": defect_material,
                            "defect_cause": defect_cause}

        if not return_rows:
            result["message"] = "未找到匹配的客退数据"
            return json.dumps(result, ensure_ascii=False, default=str)

        # ====== 2. 统计不良物料→供应商集中度 ======
        material_supplier_counter: dict[str, dict[str, int]] = {}  # {物料: {供应商: 数量}}
        batch_counter: dict[str, int] = {}  # {批次号: 数量}
        sn_list = []

        for row in return_rows:
            sn = row.get("sn_no")
            if sn:
                sn_list.append(sn)

            # 拆分多值字段
            materials = [m.strip() for m in str(row.get("defect_material") or "").split(",") if m.strip()]
            suppliers = [s.strip() for s in str(row.get("defect_material_supplier") or "").split(",") if s.strip()]
            batches = [b.strip() for b in str(row.get("defect_material_batch") or "").split(",") if b.strip()]

            for mat in materials:
                if mat not in material_supplier_counter:
                    material_supplier_counter[mat] = {}
                for sup in suppliers:
                    material_supplier_counter[mat][sup] = material_supplier_counter[mat].get(sup, 0) + 1

            for batch in batches:
                batch_counter[batch] = batch_counter.get(batch, 0) + 1

        # 整理不良物料→供应商关联
        material_supplier_analysis = []
        for mat, suppliers in material_supplier_counter.items():
            for sup, cnt in sorted(suppliers.items(), key=lambda x: x[1], reverse=True):
                material_supplier_analysis.append({
                    "defect_material": mat,
                    "supplier": sup,
                    "affected_count": cnt,
                })
        result["material_supplier_trace"] = material_supplier_analysis[:20]

        # 整理批次集中度
        if batch_counter:
            top_batches = sorted(batch_counter.items(), key=lambda x: x[1], reverse=True)[:10]
            result["batch_concentration"] = [
                {"batch": b, "count": c} for b, c in top_batches
            ]

        # ====== 3. 追溯SN关键物料（抽样前10个SN） ======
        sample_sns = sn_list[:10]
        if sample_sns:
            sn_materials = []
            for sn in sample_sns:
                try:
                    mats = query_table("sn_quality_key_material", where={"sn_no": sn})
                    for m in _serialize_rows(mats):
                        m["from_sn"] = sn
                        sn_materials.append(m)
                except Exception:
                    pass
            result["sn_key_materials_sample"] = sn_materials[:50]

        # ====== 4. 查询嫌疑供应商的IQC质量 ======
        suspect_suppliers = set()
        for item in material_supplier_analysis[:5]:
            sup = item.get("supplier")
            if sup:
                suspect_suppliers.add(sup)

        supplier_quality = {}
        for sup in suspect_suppliers:
            try:
                iqc = query_table("supplier_quality_iqc", where={"supplier_name": sup})
                iqc = _serialize_rows(iqc)
                monthly = query_table("supplier_quality_iqc_monthly",
                                      where={"supplier_name": sup}, order_by="ic_month")
                monthly = _serialize_rows(monthly)
                supplier_quality[sup] = {
                    "iqc_summary": iqc[:5] if iqc else [],
                    "monthly_trend": monthly[-6:] if monthly else [],
                }
            except Exception as e:
                supplier_quality[sup] = {"error": str(e)}
        result["suspect_supplier_quality"] = supplier_quality

        # ====== 5. 统计维修实际更换的物料 ======
        repair_material_counter: dict[str, int] = {}
        for sn in sample_sns:
            try:
                repairs = query_table("maintain_consume_material", where={"sn_no": sn})
                for r in repairs:
                    mat_name = r.get("maintain_material_name", "")
                    if mat_name:
                        repair_material_counter[mat_name] = repair_material_counter.get(mat_name, 0) + (r.get("consume_material_count") or 1)
            except Exception:
                pass
        if repair_material_counter:
            sorted_repairs = sorted(repair_material_counter.items(), key=lambda x: x[1], reverse=True)
            result["repair_materials"] = [
                {"material_name": k, "total_consumed": v} for k, v in sorted_repairs[:10]
            ]

        result["has_data"] = True
        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error("tool_root_cause_analysis 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ======================== 告警查询工具 ========================

def tool_get_alerts(level: str = None, limit: int = 20) -> str:
    """
    查询质量预警告警列表。

    Args:
        level: 过滤告警级别（critical/warning/info），不传则返回全部
        limit: 返回条数上限
    """
    try:
        from alert_monitor import get_alert_summary, get_alerts
        alerts = get_alerts(level=level, acknowledged=False, limit=limit)
        summary = get_alert_summary()
        return json.dumps({
            "summary": summary,
            "alerts": alerts,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.error("tool_get_alerts 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def tool_run_check_now() -> str:
    """立即执行一次质量巡检（不等定时器），返回巡检后的告警摘要。"""
    try:
        from alert_monitor import get_alert_summary, run_all_checks
        run_all_checks()
        summary = get_alert_summary()
        return json.dumps({
            "message": "巡检完成",
            "summary": summary,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("tool_run_check_now 错误: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ======================== 工具注册表 ========================
# 将工具函数映射到名称，供 agents.py 分发调用

TOOL_REGISTRY: dict[str, callable] = {
    "query_table": tool_query_table,
    "search_table": tool_search_table,
    "aggregate_query": tool_aggregate_query,
    "time_range_query": tool_time_range_query,
    "get_table_info": tool_get_table_info,
    "list_all_tables": tool_list_all_tables,
    "get_table_count": tool_get_table_count,
    "sn_full_trace": tool_sn_full_trace,
    "supplier_overview": tool_supplier_overview,
    "factory_overview": tool_factory_overview,
    "sku_overview": tool_sku_overview,
    "return_overview": tool_return_overview,
    "baseline_compare": tool_baseline_compare,
    "search_knowledge": tool_search_knowledge,
    "root_cause_analysis": tool_root_cause_analysis,
    "get_alerts": tool_get_alerts,
    "run_check_now": tool_run_check_now,
}


def execute_tool(tool_name: str, arguments: dict, user: str = None) -> str:
    """根据名称执行工具，返回 JSON 字符串结果"""
    func = TOOL_REGISTRY.get(tool_name)
    if func is None:
        return json.dumps({"error": f"未知工具: {tool_name}"}, ensure_ascii=False)
    try:
        # 对需要 MCP 调用的工具，注入 _user 参数
        if tool_name == "return_overview" and user:
            arguments["_user"] = user
        return func(**arguments)
    except TypeError as e:
        return json.dumps({"error": f"工具参数错误: {e}"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("工具执行异常: %s", tool_name)
        return json.dumps({"error": f"工具执行失败: {e}"}, ensure_ascii=False)


# ======================== OpenAI Function Calling Schema ========================
# 定义 tools 参数给 LLM，让 LLM 知道可以调用哪些工具

OPENAI_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "query_table",
            "description": "查询指定的质量数据表，支持按条件过滤、排序和限制返回条数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {
                        "type": "string",
                        "description": "表的key名称",
                        "enum": [
                            "sn_quality_data", "sn_quality_key_material",
                            "supplier_quality_iqc", "supplier_quality_iqc_monthly",
                            "supplier_performance_comparison",
                            "sku_quality", "sku_quality_monthly",
                            "factory_quality", "factory_quality_monthly",
                            "part_quality", "part_quality_monthly",
                            "iqc_ng", "pqc_ng", "oqc_ng",
                            "return_data", "maintain_consume_material",
                        ],
                    },
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要查询的列名列表，不传则查全部列",
                    },
                    "where": {
                        "type": "object",
                        "description": "等值过滤条件，格式为 {列名: 值} 或 {列名: [值1, 值2]}",
                    },
                    "order_by": {
                        "type": "string",
                        "description": "排序字段，前缀'-'表示降序，例如 '-退货率'",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回行数上限，默认0表示不限制，返回全部符合条件的数据",
                    },
                },
                "required": ["table_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_table",
            "description": "在指定表中对某一列进行模糊搜索（LIKE匹配）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "description": "表的key名称"},
                    "column": {"type": "string", "description": "要搜索的列名"},
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认0表示不限制"},
                },
                "required": ["table_key", "column", "keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregate_query",
            "description": "对质量数据表进行聚合统计（AVG/SUM/COUNT/MAX/MIN），按指定字段分组。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "description": "表的key名称"},
                    "group_by": {"type": "string", "description": "分组字段"},
                    "agg_column": {"type": "string", "description": "聚合计算的列"},
                    "agg_func": {
                        "type": "string",
                        "enum": ["AVG", "SUM", "COUNT", "MAX", "MIN"],
                        "description": "聚合函数，默认AVG",
                    },
                    "where": {"type": "object", "description": "过滤条件"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认0表示不限制"},
                },
                "required": ["table_key", "group_by", "agg_column"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "time_range_query",
            "description": "按时间范围查询质量数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "description": "表的key名称"},
                    "time_column": {"type": "string", "description": "时间列名称"},
                    "start": {"type": "string", "description": "起始时间，格式 YYYY-MM-DD"},
                    "end": {"type": "string", "description": "结束时间，格式 YYYY-MM-DD"},
                    "columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要查询的列",
                    },
                    "where": {"type": "object", "description": "额外过滤条件"},
                    "limit": {"type": "integer", "description": "返回行数上限，默认0表示不限制"},
                },
                "required": ["table_key", "time_column", "start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_info",
            "description": "获取指定质量数据表的元信息，包括描述、数据来源、全部字段列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "description": "表的key名称"},
                },
                "required": ["table_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_all_tables",
            "description": "列出全部可用的质量数据表及其描述信息。无需参数。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_table_count",
            "description": "获取指定表的数据行数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_key": {"type": "string", "description": "表的key名称"},
                },
                "required": ["table_key"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sn_full_trace",
            "description": "SN全链路溯源：输入SN序列号，一次性查询该SN的生产/出货/客退质量数据和使用的关键物料数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sn": {"type": "string", "description": "产品序列号SN"},
                },
                "required": ["sn"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "supplier_overview",
            "description": "供应商质量概览：输入供应商名称，一次性查询该供应商的IQC数据、月度趋势和横向对比数据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "supplier": {"type": "string", "description": "供应商名称"},
                },
                "required": ["supplier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "factory_overview",
            "description": "代工厂质量概览：输入代工厂名称，一次性查询该工厂的整体质量数据和月度趋势。",
            "parameters": {
                "type": "object",
                "properties": {
                    "factory": {"type": "string", "description": "代工厂/生产工厂名称"},
                },
                "required": ["factory"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sku_overview",
            "description": "SKU质量概览：输入SKU名称，一次性查询该SKU的整体质量数据和月度趋势。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_name": {"type": "string", "description": "SKU名称"},
                },
                "required": ["sku_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "return_overview",
            "description": "客退分析报告数据：一次性返回7个维度的结构化分析数据，包括整体概况（退货数/复测完成率/返修完成率）、受理原因四分类（质量/7无/付费换新/其他）、复测结果分布、不良原因TOP5（多值拆分）、不良物料TOP5（多值拆分）、责任归属TOP10（多值拆分）、处理状况分布。可按SKU名称或生产工厂过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_name": {"type": "string", "description": "按SKU名称模糊过滤（可选），如输入'4 Lite'可匹配'米家空气净化器 4 Lite'"},
                    "factory": {"type": "string", "description": "按生产工厂模糊过滤（可选）"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "baseline_compare",
            "description": "将实际质量指标与基线标准进行对比，返回判定结果（正常/预警/严重）。可对比退货率、供应商IQC抽检不合格次数、代工厂直通率等指标。在查询到实际数据后应主动调用此工具进行基线对比。",
            "parameters": {
                "type": "object",
                "properties": {
                    "indicator": {"type": "string", "description": "指标名称，如'退货率'、'IQC抽检不合格次数'、'直通率'"},
                    "actual_value": {"type": "number", "description": "实际数值（退货率为百分比如2.5表示2.5%，IQC不合格次数为整数如3）"},
                    "sku_category": {"type": "string", "description": "SKU类别（退货率对比时需要），如'空气净化器'、'扫地机器人'"},
                    "compare_type": {
                        "type": "string",
                        "enum": ["退货率", "供应商IQC", "代工厂"],
                        "description": "对比类型，默认'退货率'",
                    },
                },
                "required": ["indicator", "actual_value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "在质量知识库中检索相关知识，包括基线标准、质量术语解释、历史分析案例。当需要了解质量专业概念或查找历史类似问题时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词，如'主板不良'、'IQC是什么'、'退货率基线'"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "root_cause_analysis",
            "description": "根因推理链分析：跨表关联客退数据、SN物料、供应商质量，一次性构建完整证据链。返回不良物料→供应商追溯、批次集中度、嫌疑供应商IQC质量、维修实际更换物料等多维度关联数据。适用于需要深入追溯退货根本原因的场景。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku_name": {"type": "string", "description": "按SKU名称过滤（可选），如'米家空气净化器 4 Lite'"},
                    "defect_material": {"type": "string", "description": "按不良物料名称过滤（可选），聚焦特定物料的根因追溯"},
                    "defect_cause": {"type": "string", "description": "按不良原因过滤（可选），聚焦特定故障类型的根因追溯"},
                    "limit": {"type": "integer", "description": "最大分析SN数量，默认50"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_alerts",
            "description": "查询质量预警告警列表。系统每4小时自动巡检，检测退货量突增、不良集中、供应商IQC不达标、复测积压等异常。返回未确认的告警及统计摘要。",
            "parameters": {
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["critical", "warning", "info"],
                        "description": "过滤告警级别（可选），不传则返回全部",
                    },
                    "limit": {"type": "integer", "description": "返回条数上限，默认20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_check_now",
            "description": "立即执行一次质量巡检（不等定时器），检测所有预警规则并返回告警摘要。当用户要求'检查一下当前质量状况'或'立即巡检'时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]
