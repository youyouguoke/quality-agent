"""
质量管理 AI Agent 系统 - MCP 客户端
封装对 MCP (Model Context Protocol) Streamable HTTP 服务的调用。
支持 session 管理、工具调用、SSE 响应解析。
"""
import json
import logging
import urllib.request
from typing import Any, Optional

from config import MCP_CONFIG

logger = logging.getLogger(__name__)

# ======================== MCP Session 管理 ========================

_session_id: Optional[str] = None
_initialized: bool = False


def _build_headers(session_id: Optional[str] = None) -> dict:
    """构建 MCP 请求头"""
    headers = {
        "Authorization": f"Bearer {MCP_CONFIG['auth_token']}",
        "smartmi-ua": MCP_CONFIG["user"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    return headers


def _parse_response(resp) -> tuple[Optional[dict], Optional[str]]:
    """解析 MCP 响应（支持 JSON 和 SSE 两种格式）"""
    session = resp.headers.get("Mcp-Session-Id")
    body = resp.read().decode("utf-8")
    ct = resp.headers.get("Content-Type", "")

    if "text/event-stream" in ct:
        # SSE 格式：解析 data: 行
        for line in body.strip().split("\n"):
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str:
                    return json.loads(data_str), session
        return None, session
    elif body.strip():
        return json.loads(body), session
    return None, session


def _mcp_post(payload: dict, session_id: Optional[str] = None) -> tuple[Optional[dict], Optional[str]]:
    """发送 MCP JSON-RPC 请求"""
    data = json.dumps(payload).encode("utf-8")
    headers = _build_headers(session_id)
    req = urllib.request.Request(MCP_CONFIG["url"], data=data, headers=headers)
    timeout = MCP_CONFIG["timeout"]

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _parse_response(resp)


def _ensure_initialized() -> str:
    """确保 MCP session 已初始化，返回 session_id"""
    global _session_id, _initialized

    if _initialized and _session_id:
        return _session_id

    # Step 1: Initialize
    result, sid = _mcp_post({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "quality-agent", "version": "1.0.0"},
        },
    })
    _session_id = sid
    logger.info("MCP session 已创建: %s", sid)

    # Step 2: Send initialized notification
    try:
        notify_data = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }).encode("utf-8")
        notify_req = urllib.request.Request(
            MCP_CONFIG["url"], data=notify_data,
            headers=_build_headers(sid),
        )
        with urllib.request.urlopen(notify_req, timeout=10) as resp:
            resp.read()
    except Exception:
        pass  # notification 通常无响应体

    _initialized = True
    return _session_id


def reset_session():
    """重置 MCP session（连接出错时调用）"""
    global _session_id, _initialized
    _session_id = None
    _initialized = False


# ======================== 工具调用 ========================

_call_id_counter = 10


def call_tool(tool_name: str, arguments: dict[str, Any] = None) -> dict:
    """
    调用 MCP 工具。

    Args:
        tool_name: MCP 工具名称（如 'get_return_overview'）
        arguments: 工具参数

    Returns:
        工具返回的结果字典。成功时包含 "content" 字段，失败时包含 "error" 字段。
    """
    global _call_id_counter

    if arguments is None:
        arguments = {}

    # 确保 session 已初始化
    try:
        session_id = _ensure_initialized()
    except Exception as e:
        logger.error("MCP 初始化失败: %s", e)
        reset_session()
        return {"error": f"MCP 初始化失败: {e}"}

    _call_id_counter += 1
    call_id = _call_id_counter

    try:
        result, _ = _mcp_post({
            "jsonrpc": "2.0",
            "id": call_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }, session_id=session_id)

        if result is None:
            return {"error": "MCP 返回空响应"}

        # 检查 JSON-RPC 错误
        if "error" in result:
            return {"error": result["error"]}

        # 提取 tools/call 结果
        call_result = result.get("result", {})

        # 检查 MCP 工具是否报错
        if call_result.get("isError"):
            content = call_result.get("content", [])
            error_text = content[0].get("text", "未知错误") if content else "未知错误"
            return {"error": error_text}

        # 正常结果：提取 content 中的 text
        content = call_result.get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0].get("text", "")
            # 尝试解析为 JSON
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}

        return {"content": content}

    except Exception as e:
        logger.error("MCP 工具调用失败 [%s]: %s", tool_name, e)
        # session 可能过期，重置
        reset_session()
        return {"error": f"MCP 调用失败: {e}"}
