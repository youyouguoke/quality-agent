"""
质量管理 AI Agent 系统 - 异常主动预警监控
定时巡检质量数据，发现异常自动生成告警。

巡检维度：
  1. SKU 退货量突增（环比增长超阈值）
  2. 单一不良原因/物料集中度过高
  3. 供应商 IQC 合格率低于基线
  4. 复测完成率低（积压严重）
"""
import json
import logging
import threading
import time
import urllib.request
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from config import ALERT_CONFIG

logger = logging.getLogger(__name__)


# ======================== 告警记录存储（内存） ========================

_alerts: list[dict] = []
_alerts_lock = threading.Lock()


def _add_alert(level: str, rule: str, title: str, detail: str, data: dict = None):
    """新增一条告警记录"""
    alert = {
        "id": len(_alerts) + 1,
        "time": datetime.now().isoformat(),
        "level": level,         # critical / warning / info
        "rule": rule,           # 触发的规则名
        "title": title,         # 告警标题
        "detail": detail,       # 详细描述
        "data": data or {},     # 关联数据
        "acknowledged": False,  # 是否已确认
    }

    with _alerts_lock:
        _alerts.append(alert)
        # 保留最近 N 条
        max_alerts = ALERT_CONFIG.get("max_alerts", 500)
        if len(_alerts) > max_alerts:
            _alerts[:] = _alerts[-max_alerts:]

    logger.warning("【预警】[%s] %s: %s", level.upper(), title, detail)

    # 尝试 Webhook 推送
    _try_webhook_notify(alert)

    return alert


def get_alerts(level: str = None, acknowledged: bool = None, limit: int = 50) -> list[dict]:
    """查询告警记录"""
    with _alerts_lock:
        result = list(_alerts)

    # 过滤
    if level:
        result = [a for a in result if a["level"] == level]
    if acknowledged is not None:
        result = [a for a in result if a["acknowledged"] == acknowledged]

    # 最新的在前
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


# ======================== Webhook 通知 ========================

def _try_webhook_notify(alert: dict):
    """尝试通过 Webhook 推送告警（失败静默）"""
    url = ALERT_CONFIG.get("webhook_url", "")
    if not url:
        return

    try:
        payload = json.dumps({
            "msgtype": "text",
            "text": {
                "content": f"【质量预警-{alert['level'].upper()}】\n"
                           f"{alert['title']}\n"
                           f"{alert['detail']}\n"
                           f"时间: {alert['time']}"
            }
        }, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        logger.debug("Webhook 推送失败: %s", e)


# ======================== 巡检规则 ========================

def _check_return_volume_spike():
    """规则1: SKU 退货量环比突增检测"""
    try:
        from database import execute_query

        # 查最近两个月各 SKU 的退货量
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
            return

        # 按 SKU 分组计算环比
        sku_monthly: dict[str, dict[str, int]] = defaultdict(dict)
        for r in rows:
            sku_monthly[r["sku_name"]][r["month"]] = r["cnt"]

        months = sorted(set(r["month"] for r in rows))
        if len(months) < 2:
            return

        prev_month, curr_month = months[-2], months[-1]

        for sku, monthly_data in sku_monthly.items():
            prev = monthly_data.get(prev_month, 0)
            curr = monthly_data.get(curr_month, 0)

            if prev == 0:
                continue

            growth_rate = (curr - prev) / prev * 100

            if growth_rate > 50:
                _add_alert(
                    level="critical",
                    rule="return_volume_spike",
                    title=f"{sku} 退货量环比激增 {growth_rate:.0f}%",
                    detail=f"{prev_month}: {prev}台 → {curr_month}: {curr}台，"
                           f"环比增长 {growth_rate:.1f}%，超过严重阈值(50%)",
                    data={"sku_name": sku, "prev_month": prev_month, "curr_month": curr_month,
                          "prev_count": prev, "curr_count": curr, "growth_rate": round(growth_rate, 1)},
                )
            elif growth_rate > 30:
                _add_alert(
                    level="warning",
                    rule="return_volume_spike",
                    title=f"{sku} 退货量环比增长 {growth_rate:.0f}%",
                    detail=f"{prev_month}: {prev}台 → {curr_month}: {curr}台，"
                           f"环比增长 {growth_rate:.1f}%，超过预警阈值(30%)",
                    data={"sku_name": sku, "prev_month": prev_month, "curr_month": curr_month,
                          "prev_count": prev, "curr_count": curr, "growth_rate": round(growth_rate, 1)},
                )

    except Exception as e:
        logger.error("巡检规则 [return_volume_spike] 执行失败: %s", e)


def _check_defect_concentration():
    """规则2: 不良原因/物料集中度过高检测"""
    try:
        from database import execute_query

        # 查最近一个月各 SKU 的不良原因分布
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
            return

        # 按 SKU 统计总量和单项占比
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
                continue  # 样本太少，跳过

            ratio = cnt / total * 100
            if ratio > 50:
                _add_alert(
                    level="critical",
                    rule="defect_concentration",
                    title=f"{sku} 不良原因高度集中: {cause}",
                    detail=f"不良原因「{cause}」占比 {ratio:.1f}%（{cnt}/{total}），"
                           f"超过严重阈值(50%)，建议专项根因分析",
                    data={"sku_name": sku, "defect_cause": cause,
                          "count": cnt, "total": total, "ratio": round(ratio, 1)},
                )
            elif ratio > 40:
                _add_alert(
                    level="warning",
                    rule="defect_concentration",
                    title=f"{sku} 不良原因集中: {cause}",
                    detail=f"不良原因「{cause}」占比 {ratio:.1f}%（{cnt}/{total}），"
                           f"超过预警阈值(40%)",
                    data={"sku_name": sku, "defect_cause": cause,
                          "count": cnt, "total": total, "ratio": round(ratio, 1)},
                )

    except Exception as e:
        logger.error("巡检规则 [defect_concentration] 执行失败: %s", e)


def _check_supplier_iqc():
    """规则3: 供应商月度 IQC 抽检不合格次数检测"""
    try:
        from database import execute_query

        # 查每个供应商的进料批次和合格批次，计算不合格次数
        sql = """
            SELECT supplier_name,
                   COALESCE(iqc_batch, 0) AS iqc_batch,
                   COALESCE(qualified_batch, 0) AS qualified_batch
            FROM supplier_quality_iqc
            WHERE iqc_batch IS NOT NULL
        """
        rows = execute_query(sql)
        if not rows:
            return

        for r in rows:
            supplier = r["supplier_name"]
            try:
                iqc_batch = int(r["iqc_batch"])
                qualified_batch = int(r["qualified_batch"])
            except (ValueError, TypeError):
                continue

            unqualified = iqc_batch - qualified_batch
            if unqualified <= 0:
                continue

            if unqualified > 3:
                _add_alert(
                    level="critical",
                    rule="supplier_iqc_unqualified",
                    title=f"供应商 {supplier} 月度IQC抽检不合格次数过多",
                    detail=f"IQC抽检不合格 {unqualified} 次（进料{iqc_batch}批/合格{qualified_batch}批），"
                           f"超过严重阈值(>3次)，需立即改善",
                    data={"supplier_name": supplier, "iqc_batch": iqc_batch,
                          "qualified_batch": qualified_batch, "unqualified": unqualified},
                )
            elif unqualified > 2:
                _add_alert(
                    level="warning",
                    rule="supplier_iqc_unqualified",
                    title=f"供应商 {supplier} 月度IQC抽检不合格次数偏多",
                    detail=f"IQC抽检不合格 {unqualified} 次（进料{iqc_batch}批/合格{qualified_batch}批），"
                           f"超过预警阈值(>2次)",
                    data={"supplier_name": supplier, "iqc_batch": iqc_batch,
                          "qualified_batch": qualified_batch, "unqualified": unqualified},
                )

    except Exception as e:
        logger.error("巡检规则 [supplier_iqc_unqualified] 执行失败: %s", e)


def _check_retest_backlog():
    """规则4: SKU 复测完成率检测"""
    try:
        from database import execute_query

        sql = """
            SELECT sku_name,
                   COUNT(*) AS total,
                   SUM(CASE WHEN retest_result IS NOT NULL AND retest_result != '' THEN 1 ELSE 0 END) AS retested
            FROM return_data
            WHERE return_time >= DATE_SUB(CURDATE(), INTERVAL 2 MONTH)
            GROUP BY sku_name
            HAVING total >= 10
        """
        rows = execute_query(sql)
        if not rows:
            return

        for r in rows:
            sku = r["sku_name"]
            total = r["total"]
            retested = r["retested"] or 0
            completion_rate = retested / total * 100 if total else 100

            if completion_rate < 60:
                _add_alert(
                    level="critical",
                    rule="retest_backlog",
                    title=f"{sku} SKU复测完成率严重偏低",
                    detail=f"SKU复测完成率仅 {completion_rate:.1f}%（{retested}/{total}），"
                           f"低于严重阈值(60%)，需立即催办",
                    data={"sku_name": sku, "total": total, "retested": retested,
                          "completion_rate": round(completion_rate, 1)},
                )
            elif completion_rate < 80:
                _add_alert(
                    level="warning",
                    rule="retest_backlog",
                    title=f"{sku} SKU复测完成率偏低",
                    detail=f"SKU复测完成率 {completion_rate:.1f}%（{retested}/{total}），"
                           f"低于预警阈值(80%)",
                    data={"sku_name": sku, "total": total, "retested": retested,
                          "completion_rate": round(completion_rate, 1)},
                )

    except Exception as e:
        logger.error("巡检规则 [retest_backlog] 执行失败: %s", e)


# ======================== 巡检引擎 ========================

ALL_CHECK_RULES = [
    ("return_volume_spike", _check_return_volume_spike),
    ("defect_concentration", _check_defect_concentration),
    ("supplier_iqc_unqualified", _check_supplier_iqc),
    ("retest_backlog", _check_retest_backlog),
]


def run_all_checks():
    """执行所有巡检规则（一次完整巡检）"""
    logger.info("开始质量巡检...")
    start = time.time()

    for name, func in ALL_CHECK_RULES:
        try:
            func()
        except Exception as e:
            logger.error("巡检规则 [%s] 异常: %s", name, e)

    elapsed = time.time() - start
    summary = get_alert_summary()
    logger.info(
        "质量巡检完成 (%.1fs)，当前告警: %d条未确认 (严重:%d, 预警:%d)",
        elapsed, summary["unacknowledged"], summary["critical"], summary["warning"],
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
        # 启动后延迟 60 秒执行首次巡检（等数据库连接就绪）
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
