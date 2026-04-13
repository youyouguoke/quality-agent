"""
质量管理 AI Agent 系统 - 异常主动预警监控
定时巡检质量数据，发现异常自动生成告警，同类告警整合为表格统一推送飞书。

巡检维度：
  1. SKU 退货量突增（环比增长超阈值）
  2. 单一不良原因/物料集中度过高
  3. 供应商当月 IQC 抽检不合格次数过多
  4. SKU 复测完成率低（积压严重）
"""
import json
import logging
import threading
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from typing import Optional

from config import ALERT_CONFIG

logger = logging.getLogger(__name__)


# ======================== 告警记录存储（内存） ========================

_alerts: list[dict] = []
_alerts_lock = threading.Lock()


def _add_alert(level: str, rule: str, title: str, detail: str, data: dict = None):
    """新增一条告警记录（仅存储，不推送飞书，推送在巡检完成后统一执行）"""
    alert = {
        "id": len(_alerts) + 1,
        "time": datetime.now().isoformat(),
        "level": level,
        "rule": rule,
        "title": title,
        "detail": detail,
        "data": data or {},
        "acknowledged": False,
    }

    with _alerts_lock:
        _alerts.append(alert)
        max_alerts = ALERT_CONFIG.get("max_alerts", 500)
        if len(_alerts) > max_alerts:
            _alerts[:] = _alerts[-max_alerts:]

    logger.warning("【预警】[%s] %s: %s", level.upper(), title, detail)
    return alert


def get_alerts(level: str = None, acknowledged: bool = None, limit: int = 50) -> list[dict]:
    """查询告警记录"""
    with _alerts_lock:
        result = list(_alerts)
    if level:
        result = [a for a in result if a["level"] == level]
    if acknowledged is not None:
        result = [a for a in result if a["acknowledged"] == acknowledged]
    result.reverse()
    return result[:limit]


def acknowledge_alert(alert_id: int) -> bool:
    """确认（消除）一条告警"""
    with _alerts_lock:
        for alert in _alerts:
            if alert["id"] == alert_id:
                alert["acknowledged"] = True
                return True
    return False


def get_alert_summary() -> dict:
    """获取告警统计摘要"""
    with _alerts_lock:
        total = len(_alerts)
        unacked = sum(1 for a in _alerts if not a["acknowledged"])
        by_level = defaultdict(int)
        for a in _alerts:
            if not a["acknowledged"]:
                by_level[a["level"]] += 1
    return {
        "total": total,
        "unacknowledged": unacked,
        "critical": by_level.get("critical", 0),
        "warning": by_level.get("warning", 0),
        "info": by_level.get("info", 0),
    }


# ======================== 飞书 Webhook 推送（整合版） ========================

_LEVEL_COLORS = {"critical": "red", "warning": "orange", "info": "blue"}
_LEVEL_LABELS = {"critical": "🔴 严重", "warning": "🟡 预警", "info": "🔵 信息"}

# 规则的中文名称
_RULE_NAMES = {
    "return_volume_spike": "退货量环比突增",
    "defect_concentration": "不良原因集中",
    "supplier_iqc_unqualified": "供应商IQC异常",
    "retest_backlog": "SKU复测积压",
}


def _send_feishu_card(title: str, color: str, elements: list):
    """发送飞书卡片消息"""
    url = ALERT_CONFIG.get("webhook_url", "")
    if not url:
        return

    try:
        payload = json.dumps({
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": color,
                },
                "elements": elements,
            },
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        logger.debug("飞书 Webhook 推送失败: %s", e)


def _build_table_rows(alerts: list[dict], columns: list[dict]) -> str:
    """
    将同类告警构建为 Markdown 表格。
    columns: [{"key": "data字段名", "header": "列标题"}, ...]
    """
    # 表头
    headers = " | ".join(col["header"] for col in columns)
    sep = " | ".join("---" for _ in columns)
    lines = [f"| {headers} |", f"| {sep} |"]

    for alert in alerts:
        data = alert.get("data", {})
        level_label = _LEVEL_LABELS.get(alert["level"], alert["level"])
        row_values = []
        for col in columns:
            key = col["key"]
            if key == "_level":
                row_values.append(level_label)
            elif key in data:
                row_values.append(str(data[key]))
            else:
                row_values.append("-")
        lines.append(f"| {' | '.join(row_values)} |")

    return "\n".join(lines)


# 每种规则的表格列定义
_RULE_TABLE_COLUMNS = {
    "return_volume_spike": [
        {"key": "_level", "header": "级别"},
        {"key": "sku_name", "header": "SKU"},
        {"key": "prev_month", "header": "上月"},
        {"key": "prev_count", "header": "上月退货"},
        {"key": "curr_month", "header": "本月"},
        {"key": "curr_count", "header": "本月退货"},
        {"key": "growth_rate", "header": "环比增长%"},
    ],
    "defect_concentration": [
        {"key": "_level", "header": "级别"},
        {"key": "sku_name", "header": "SKU"},
        {"key": "defect_cause", "header": "不良原因"},
        {"key": "count", "header": "数量"},
        {"key": "total", "header": "总数"},
        {"key": "ratio", "header": "占比%"},
    ],
    "supplier_iqc_unqualified": [
        {"key": "_level", "header": "级别"},
        {"key": "supplier_name", "header": "供应商"},
        {"key": "month", "header": "月份"},
        {"key": "iqc_batch", "header": "进料批次"},
        {"key": "qualified_batch", "header": "合格批次"},
        {"key": "unqualified", "header": "不合格次数"},
    ],
    "retest_backlog": [
        {"key": "_level", "header": "级别"},
        {"key": "sku_name", "header": "SKU"},
        {"key": "total", "header": "退货总数"},
        {"key": "retested", "header": "已复测"},
        {"key": "completion_rate", "header": "完成率%"},
    ],
}


def _batch_notify_feishu(new_alerts: list[dict]):
    """将本轮巡检产生的告警按规则分组，每组整合为一个表格卡片发送"""
    if not new_alerts:
        return

    url = ALERT_CONFIG.get("webhook_url", "")
    if not url:
        return

    # 按规则分组
    by_rule: dict[str, list[dict]] = defaultdict(list)
    for alert in new_alerts:
        by_rule[alert["rule"]].append(alert)

    for rule, alerts in by_rule.items():
        # 确定卡片颜色：有 critical 就红色，否则橙色
        has_critical = any(a["level"] == "critical" for a in alerts)
        color = "red" if has_critical else "orange"
        rule_name = _RULE_NAMES.get(rule, rule)

        # 构建表格
        columns = _RULE_TABLE_COLUMNS.get(rule)
        if columns:
            table_md = _build_table_rows(alerts, columns)
        else:
            # 无预定义列定义时，用简单列表
            table_md = "\n".join(f"- {a['title']}: {a['detail']}" for a in alerts)

        elements = [
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{rule_name}** 共 {len(alerts)} 条告警\n\n{table_md}"},
            },
            {
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": f"巡检时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"}],
            },
        ]

        _send_feishu_card(f"质量预警 | {rule_name}（{len(alerts)}条）", color, elements)


# ======================== 巡检规则 ========================

def _check_return_volume_spike() -> list[dict]:
    """规则1: SKU 退货量环比突增检测"""
    new_alerts = []
    try:
        from database import execute_query

        sql = """
            SELECT sku_name,
                   DATE_FORMAT(return_time, '%%Y-%%m') AS month,
                   COUNT(*) AS cnt
            FROM return_data
            WHERE return_time >= DATE_SUB(CURDATE(), INTERVAL 2 MONTH)
            GROUP BY sku_name, DATE_FORMAT(return_time, '%%Y-%%m')
            ORDER BY sku_name, month
        """
        rows = execute_query(sql)
        if not rows:
            return new_alerts

        sku_monthly: dict[str, dict[str, int]] = defaultdict(dict)
        for r in rows:
            sku_monthly[r["sku_name"]][r["month"]] = r["cnt"]

        months = sorted(set(r["month"] for r in rows))
        if len(months) < 2:
            return new_alerts

        prev_month, curr_month = months[-2], months[-1]

        for sku, monthly_data in sku_monthly.items():
            prev = monthly_data.get(prev_month, 0)
            curr = monthly_data.get(curr_month, 0)
            if prev == 0:
                continue
            growth_rate = (curr - prev) / prev * 100

            if growth_rate > 50:
                new_alerts.append(_add_alert(
                    level="critical", rule="return_volume_spike",
                    title=f"{sku} 退货量环比激增 {growth_rate:.0f}%",
                    detail=f"{prev_month}: {prev}台 → {curr_month}: {curr}台，环比增长 {growth_rate:.1f}%",
                    data={"sku_name": sku, "prev_month": prev_month, "curr_month": curr_month,
                          "prev_count": prev, "curr_count": curr, "growth_rate": round(growth_rate, 1)},
                ))
            elif growth_rate > 30:
                new_alerts.append(_add_alert(
                    level="warning", rule="return_volume_spike",
                    title=f"{sku} 退货量环比增长 {growth_rate:.0f}%",
                    detail=f"{prev_month}: {prev}台 → {curr_month}: {curr}台，环比增长 {growth_rate:.1f}%",
                    data={"sku_name": sku, "prev_month": prev_month, "curr_month": curr_month,
                          "prev_count": prev, "curr_count": curr, "growth_rate": round(growth_rate, 1)},
                ))
    except Exception as e:
        logger.error("巡检规则 [return_volume_spike] 执行失败: %s", e)
    return new_alerts


def _check_defect_concentration() -> list[dict]:
    """规则2: 不良原因/物料集中度过高检测"""
    new_alerts = []
    try:
        from database import execute_query

        sql = """
            SELECT sku_name, defect_cause, COUNT(*) AS cnt
            FROM return_data
            WHERE return_time >= DATE_SUB(CURDATE(), INTERVAL 1 MONTH)
              AND retest_result IS NOT NULL AND retest_result != ''
              AND defect_cause IS NOT NULL AND defect_cause != ''
            GROUP BY sku_name, defect_cause
            ORDER BY sku_name, cnt DESC
        """
        rows = execute_query(sql)
        if not rows:
            return new_alerts

        sku_total: dict[str, int] = defaultdict(int)
        sku_top: dict[str, tuple[str, int]] = {}
        for r in rows:
            sku = r["sku_name"]
            cnt = r["cnt"]
            sku_total[sku] += cnt
            if sku not in sku_top or cnt > sku_top[sku][1]:
                sku_top[sku] = (r["defect_cause"], cnt)

        for sku, (cause, cnt) in sku_top.items():
            total = sku_total[sku]
            if total < 5:
                continue
            ratio = cnt / total * 100
            if ratio > 50:
                new_alerts.append(_add_alert(
                    level="critical", rule="defect_concentration",
                    title=f"{sku} 不良原因高度集中: {cause}",
                    detail=f"不良原因「{cause}」占比 {ratio:.1f}%（{cnt}/{total}），建议专项根因分析",
                    data={"sku_name": sku, "defect_cause": cause,
                          "count": cnt, "total": total, "ratio": round(ratio, 1)},
                ))
            elif ratio > 40:
                new_alerts.append(_add_alert(
                    level="warning", rule="defect_concentration",
                    title=f"{sku} 不良原因集中: {cause}",
                    detail=f"不良原因「{cause}」占比 {ratio:.1f}%（{cnt}/{total}）",
                    data={"sku_name": sku, "defect_cause": cause,
                          "count": cnt, "total": total, "ratio": round(ratio, 1)},
                ))
    except Exception as e:
        logger.error("巡检规则 [defect_concentration] 执行失败: %s", e)
    return new_alerts


def _check_supplier_iqc() -> list[dict]:
    """规则3: 供应商月度 IQC 抽检不合格次数检测（最近一个月）"""
    new_alerts = []
    try:
        from database import execute_query

        # 取 supplier_quality_iqc_monthly 中最近一个月的月份
        latest_sql = """
            SELECT MAX(ic_month) AS latest_month
            FROM supplier_quality_iqc_monthly
        """
        latest_row = execute_query(latest_sql)
        if not latest_row or not latest_row[0].get("latest_month"):
            return new_alerts
        latest_month = latest_row[0]["latest_month"]

        # 查该月所有供应商的数据
        sql = """
            SELECT supplier_name,
                   ic_month,
                   iqc_batch_pass_rate,
                   reject_rate
            FROM supplier_quality_iqc_monthly
            WHERE ic_month = %s
        """
        rows = execute_query(sql, (latest_month,))
        if not rows:
            return new_alerts

        # 查 supplier_quality_iqc 获取进料/合格批次明细
        iqc_sql = """
            SELECT supplier_name,
                   COALESCE(iqc_batch, 0) AS iqc_batch,
                   COALESCE(qualified_batch, 0) AS qualified_batch
            FROM supplier_quality_iqc
            WHERE iqc_batch IS NOT NULL
        """
        iqc_rows = execute_query(iqc_sql)
        iqc_map = {}
        for r in (iqc_rows or []):
            iqc_map[r["supplier_name"]] = r

        for r in rows:
            supplier = r["supplier_name"]
            iqc_info = iqc_map.get(supplier, {})
            try:
                iqc_batch = int(iqc_info.get("iqc_batch", 0))
                qualified_batch = int(iqc_info.get("qualified_batch", 0))
            except (ValueError, TypeError):
                continue

            unqualified = iqc_batch - qualified_batch
            if unqualified <= 0:
                continue

            if unqualified > 3:
                new_alerts.append(_add_alert(
                    level="critical", rule="supplier_iqc_unqualified",
                    title=f"供应商 {supplier} 月度IQC抽检不合格次数过多",
                    detail=f"{latest_month} 月不合格 {unqualified} 次（进料{iqc_batch}批/合格{qualified_batch}批），超过严重阈值(>3次)",
                    data={"supplier_name": supplier, "month": latest_month,
                          "iqc_batch": iqc_batch, "qualified_batch": qualified_batch,
                          "unqualified": unqualified},
                ))
            elif unqualified > 2:
                new_alerts.append(_add_alert(
                    level="warning", rule="supplier_iqc_unqualified",
                    title=f"供应商 {supplier} 月度IQC抽检不合格次数偏多",
                    detail=f"{latest_month} 月不合格 {unqualified} 次（进料{iqc_batch}批/合格{qualified_batch}批），超过预警阈值(>2次)",
                    data={"supplier_name": supplier, "month": latest_month,
                          "iqc_batch": iqc_batch, "qualified_batch": qualified_batch,
                          "unqualified": unqualified},
                ))
    except Exception as e:
        logger.error("巡检规则 [supplier_iqc_unqualified] 执行失败: %s", e)
    return new_alerts


def _check_retest_backlog() -> list[dict]:
    """规则4: SKU 复测完成率检测（全量数据）"""
    new_alerts = []
    try:
        from database import execute_query

        sql = """
            SELECT sku_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN retest_result IS NOT NULL AND retest_result != '' THEN 1 ELSE 0 END) AS retested
            FROM return_data
            GROUP BY sku_name
            HAVING total >= 10
        """
        rows = execute_query(sql)
        if not rows:
            return new_alerts

        for r in rows:
            sku = r["sku_name"]
            total = r["total"]
            retested = r["retested"] or 0
            completion_rate = retested / total * 100 if total else 100

            if completion_rate < 60:
                new_alerts.append(_add_alert(
                    level="critical", rule="retest_backlog",
                    title=f"{sku} SKU复测完成率严重偏低",
                    detail=f"复测完成率 {completion_rate:.1f}%（{retested}/{total}），需立即催办",
                    data={"sku_name": sku, "total": total, "retested": retested,
                          "completion_rate": round(completion_rate, 1)},
                ))
            elif completion_rate < 80:
                new_alerts.append(_add_alert(
                    level="warning", rule="retest_backlog",
                    title=f"{sku} SKU复测完成率偏低",
                    detail=f"复测完成率 {completion_rate:.1f}%（{retested}/{total}）",
                    data={"sku_name": sku, "total": total, "retested": retested,
                          "completion_rate": round(completion_rate, 1)},
                ))
    except Exception as e:
        logger.error("巡检规则 [retest_backlog] 执行失败: %s", e)
    return new_alerts


# ======================== 巡检引擎 ========================

ALL_CHECK_RULES = [
    ("return_volume_spike", _check_return_volume_spike),
    ("defect_concentration", _check_defect_concentration),
    ("supplier_iqc_unqualified", _check_supplier_iqc),
    ("retest_backlog", _check_retest_backlog),
]


def run_all_checks():
    """执行所有巡检规则，完成后按规则分类整合推送飞书"""
    logger.info("开始质量巡检...")
    start = time.time()

    # 收集本轮所有新告警
    all_new_alerts: list[dict] = []
    for name, func in ALL_CHECK_RULES:
        try:
            new_alerts = func()
            all_new_alerts.extend(new_alerts)
        except Exception as e:
            logger.error("巡检规则 [%s] 异常: %s", name, e)

    # 统一推送飞书（同类告警整合为一张表格卡片）
    _batch_notify_feishu(all_new_alerts)

    elapsed = time.time() - start
    summary = get_alert_summary()
    logger.info(
        "质量巡检完成 (%.1fs)，本轮新增告警: %d条，当前未确认: %d条 (严重:%d, 预警:%d)",
        elapsed, len(all_new_alerts), summary["unacknowledged"],
        summary["critical"], summary["warning"],
    )


# ======================== 定时巡检线程 ========================

_monitor_thread: Optional[threading.Thread] = None
_monitor_running = False


def start_monitor():
    """启动后台巡检线程"""
    global _monitor_thread, _monitor_running

    if not ALERT_CONFIG.get("enabled", True):
        logger.info("预警监控已禁用 (ALERT_ENABLED=false)")
        return

    if _monitor_running:
        logger.warning("巡检线程已在运行")
        return

    _monitor_running = True
    interval = ALERT_CONFIG.get("check_interval", 14400)

    def _loop():
        time.sleep(60)
        while _monitor_running:
            try:
                run_all_checks()
            except Exception as e:
                logger.error("巡检循环异常: %s", e)
            time.sleep(interval)

    _monitor_thread = threading.Thread(target=_loop, name="alert-monitor", daemon=True)
    _monitor_thread.start()
    logger.info("预警监控已启动，巡检间隔: %d秒", interval)


def stop_monitor():
    """停止巡检线程"""
    global _monitor_running
    _monitor_running = False
    logger.info("预警监控已停止")
