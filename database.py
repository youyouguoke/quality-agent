"""
质量管理 AI Agent 系统 - 数据库访问层
连接现有 MySQL 数据库，封装对质量数据资产表的查询方法。
"""
import logging
from contextlib import contextmanager
from typing import Any, Optional

import mysql.connector

from config import DB_CONFIG, TABLE_NAMES, TABLE_SCHEMAS, UNAVAILABLE_TABLES

logger = logging.getLogger(__name__)


# ======================== 连接管理 ========================

def _create_connection():
    """创建一个新的 MySQL 连接"""
    return mysql.connector.connect(
        host=DB_CONFIG["host"],
        port=DB_CONFIG["port"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        charset=DB_CONFIG["charset"],
        connection_timeout=30,
        autocommit=True,
    )


def get_pool():
    """健康检查用：测试能否连接数据库"""
    conn = _create_connection()
    conn.close()
    return True


@contextmanager
def get_connection():
    """获取连接（上下文管理器，用完自动关闭）"""
    conn = _create_connection()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _resolve_table(table_key: str) -> str:
    """将内部表key映射为实际MySQL表名，检查是否可用"""
    if table_key in UNAVAILABLE_TABLES:
        raise ValueError(
            f"表 {table_key} 当前不可用（数据库中尚未创建），"
            f"当前可用的表: {[k for k in TABLE_NAMES if k not in UNAVAILABLE_TABLES]}"
        )
    real_name = TABLE_NAMES.get(table_key)
    if real_name is None:
        raise ValueError(f"未知的表key: {table_key}，可用的表: {list(TABLE_NAMES.keys())}")
    return real_name


def _validate_columns(table_key: str, columns: list[str]) -> list[str]:
    """校验请求的列名是否在表schema中，防止SQL注入"""
    schema = TABLE_SCHEMAS.get(table_key)
    if schema is None:
        raise ValueError(f"未找到表 {table_key} 的schema定义")
    allowed = set(schema["columns"])
    invalid = [c for c in columns if c not in allowed]
    if invalid:
        raise ValueError(f"表 {table_key} 不包含列: {invalid}，可用列: {schema['columns']}")
    return columns


# ======================== 通用查询方法 ========================

def execute_query(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    """执行原始SQL查询，返回字典列表"""
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        results = cursor.fetchall()
        cursor.close()
    return results


def query_table(
    table_key: str,
    columns: Optional[list[str]] = None,
    where: Optional[dict[str, Any]] = None,
    order_by: Optional[str] = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """
    安全查询指定质量数据表。
    - table_key: 表的内部key（如 'sn_quality_data'）
    - columns: 要查询的列，None则查全部
    - where: 等值过滤条件 {列名: 值}
    - order_by: 排序字段
    - limit: 返回行数上限，0表示不限制
    """
    real_table = _resolve_table(table_key)

    # 构建 SELECT
    if columns:
        _validate_columns(table_key, columns)
        cols_sql = ", ".join(f"`{c}`" for c in columns)
    else:
        cols_sql = "*"

    sql = f"SELECT {cols_sql} FROM `{real_table}`"
    params: list[Any] = []

    # 构建 WHERE
    if where:
        _validate_columns(table_key, list(where.keys()))
        conditions = []
        for col, val in where.items():
            if isinstance(val, list):
                placeholders = ", ".join(["%s"] * len(val))
                conditions.append(f"`{col}` IN ({placeholders})")
                params.extend(val)
            else:
                conditions.append(f"`{col}` = %s")
                params.append(val)
        sql += " WHERE " + " AND ".join(conditions)

    # ORDER BY
    if order_by:
        # 简单校验order_by防止注入
        order_col = order_by.lstrip("-")
        schema = TABLE_SCHEMAS.get(table_key)
        if schema and order_col in schema["columns"]:
            direction = "DESC" if order_by.startswith("-") else "ASC"
            sql += f" ORDER BY `{order_col}` {direction}"

    # LIMIT
    if limit > 0:
        sql += f" LIMIT {limit}"

    return execute_query(sql, tuple(params))


def query_table_like(
    table_key: str,
    column: str,
    keyword: str,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """模糊查询"""
    real_table = _resolve_table(table_key)
    _validate_columns(table_key, [column])
    sql = f"SELECT * FROM `{real_table}` WHERE `{column}` LIKE %s"
    if limit > 0:
        sql += f" LIMIT {limit}"
    return execute_query(sql, (f"%{keyword}%",))


def query_table_aggregate(
    table_key: str,
    group_by: str,
    agg_column: str,
    agg_func: str = "AVG",
    where: Optional[dict[str, Any]] = None,
    order_by_agg: bool = True,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """
    聚合查询（AVG/SUM/COUNT/MAX/MIN）。
    """
    real_table = _resolve_table(table_key)
    _validate_columns(table_key, [group_by, agg_column])

    agg_func = agg_func.upper()
    if agg_func not in ("AVG", "SUM", "COUNT", "MAX", "MIN"):
        raise ValueError(f"不支持的聚合函数: {agg_func}")

    sql = f"SELECT `{group_by}`, {agg_func}(`{agg_column}`) AS `{agg_func}_{agg_column}` FROM `{real_table}`"
    params: list[Any] = []

    if where:
        _validate_columns(table_key, list(where.keys()))
        conditions = []
        for col, val in where.items():
            conditions.append(f"`{col}` = %s")
            params.append(val)
        sql += " WHERE " + " AND ".join(conditions)

    sql += f" GROUP BY `{group_by}`"

    if order_by_agg:
        sql += f" ORDER BY `{agg_func}_{agg_column}` DESC"

    if limit > 0:
        sql += f" LIMIT {limit}"

    return execute_query(sql, tuple(params))


def query_table_time_range(
    table_key: str,
    time_column: str,
    start: str,
    end: str,
    columns: Optional[list[str]] = None,
    where: Optional[dict[str, Any]] = None,
    limit: int = 0,
) -> list[dict[str, Any]]:
    """时间范围查询"""
    real_table = _resolve_table(table_key)
    _validate_columns(table_key, [time_column])

    if columns:
        _validate_columns(table_key, columns)
        cols_sql = ", ".join(f"`{c}`" for c in columns)
    else:
        cols_sql = "*"

    sql = f"SELECT {cols_sql} FROM `{real_table}` WHERE `{time_column}` BETWEEN %s AND %s"
    params: list[Any] = [start, end]

    if where:
        _validate_columns(table_key, list(where.keys()))
        for col, val in where.items():
            sql += f" AND `{col}` = %s"
            params.append(val)

    sql += f" ORDER BY `{time_column}` DESC"
    if limit > 0:
        sql += f" LIMIT {limit}"

    return execute_query(sql, tuple(params))


# ======================== 元数据查询 ========================

def get_table_info(table_key: str) -> dict:
    """获取表的元信息（描述、来源、字段列表、字段中文映射、是否可用）"""
    schema = TABLE_SCHEMAS.get(table_key)
    if schema is None:
        raise ValueError(f"未找到表 {table_key} 的定义")
    return {
        "table_key": table_key,
        "real_table_name": TABLE_NAMES.get(table_key),
        "description": schema["description"],
        "source": schema["source"],
        "columns": schema["columns"],
        "column_mapping": schema.get("column_mapping", {}),
        "available": table_key not in UNAVAILABLE_TABLES,
    }


def get_all_table_info() -> list[dict]:
    """获取全部质量数据表的元信息"""
    return [get_table_info(key) for key in TABLE_SCHEMAS]


def get_table_row_count(table_key: str) -> int:
    """获取表的行数"""
    real_table = _resolve_table(table_key)
    result = execute_query(f"SELECT COUNT(*) AS cnt FROM `{real_table}`")
    return result[0]["cnt"] if result else 0
