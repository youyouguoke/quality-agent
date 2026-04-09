"""
质量管理 AI Agent 系统 - FastAPI 服务入口
提供 HTTP API 接口供智能体管理平台注册和调用。

平台注册信息：
  ID:       quality_agent
  类型:     HTTP服务
  服务地址: http://<host>:<port>/agent/chat
  描述:     基于质量数据资产的智能分析Agent，支持SN溯源、供应商分析、
           SKU分析、代工厂分析、物料分析和根因分析等质量管理场景

接口：
  POST   /agent/chat          - 对话接口（核心，平台调用此接口）
  GET    /agent/health        - 健康检查
  GET    /agent/tables        - 查看可用的质量数据表
  DELETE /agent/session/{id}  - 清除会话

启动: uvicorn app:app --host 0.0.0.0 --port 8000
"""
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from agents import clear_session, run_master_agent
from alert_monitor import (
    acknowledge_alert,
    get_alert_summary,
    get_alerts,
    run_all_checks,
    start_monitor,
    stop_monitor,
)
from config import API_CONFIG, LLM_CONFIG
from database import get_all_table_info, get_pool
from models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthStatus,
)
from user_profile import get_profile, update_profile

# ======================== 日志配置 ========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ======================== 应用生命周期 ========================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动/关闭时的初始化和清理"""
    logger.info("质量管理 AI Agent 系统启动中...")
    try:
        get_pool()
        logger.info("MySQL 连接池就绪")
    except Exception as e:
        logger.warning("MySQL 连接池初始化失败（服务仍启动，查询时会重试）: %s", e)

    # 启动质量预警巡检线程
    start_monitor()

    yield

    # 停止巡检线程
    stop_monitor()
    logger.info("质量管理 AI Agent 系统已关闭")


# ======================== FastAPI 应用 ========================
app = FastAPI(
    title="质量管理 AI Agent",
    description=(
        "基于质量数据资产的智能分析Agent系统，支持SN溯源、供应商分析、SKU分析、"
        "代工厂分析、物料分析和根因分析等质量管理场景。\n\n"
        "平台通过 POST /agent/chat 接口调用，请求体: {\"message\": \"用户问题\"}"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================== 核心接口：对话 ========================

@app.post(
    "/agent/chat",
    response_model=ChatResponse,
    responses={500: {"model": ErrorResponse}},
    summary="对话接口",
    description="智能体管理平台调用此接口与质量管理Agent进行自然语言交互。",
)
async def chat(request: ChatRequest, raw_request: Request):
    """
    核心对话接口 - 与智能体管理平台对齐（参照OA agent协议）。

    请求示例：
    ```json
    {"message": "查询SN12345678的全链路质量数据"}
    ```
    响应示例：
    ```json
    {"message": "该SN的生产数据如下..."}
    ```
    """
    # 从请求头提取调用用户（smartmi-ua），透传给 MCP 调用
    caller_user = raw_request.headers.get("smartmi-ua")
    logger.info("请求头: %s", dict(raw_request.headers))

    start_time = time.time()

    try:
        result = run_master_agent(
            query=request.message,
            session_id=request.session_id,
            user=caller_user,
        )

        elapsed = time.time() - start_time
        logger.info(
            "对话完成 [session=%s, agent=%s, rounds=%s, time=%.2fs]",
            result["session_id"],
            result["agent_used"],
            result.get("metadata", {}).get("rounds", "?"),
            elapsed,
        )

        return ChatResponse(
            message=result["answer"],
            session_id=result["session_id"],
            agent_used=result["agent_used"],
            steps=result.get("steps", []),
            data=result.get("data"),
        )

    except Exception as e:
        logger.exception("对话处理异常")
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 健康检查 ========================

@app.get(
    "/agent/health",
    response_model=HealthStatus,
    summary="健康检查",
)
async def health_check():
    """检查服务、数据库和LLM连接的健康状态"""
    db_status = "unknown"
    try:
        get_pool()
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {e}"

    llm_status = "configured" if LLM_CONFIG["api_key"] else "not_configured"

    return HealthStatus(
        status="healthy",
        version="1.0.0",
        database=db_status,
        llm=llm_status,
        timestamp=datetime.now(),
    )


# ======================== 数据资产查询 ========================

@app.get(
    "/agent/tables",
    summary="查看可用的质量数据表",
    description="列出系统中所有可查询的质量数据资产表及其字段信息。",
)
async def list_tables():
    """返回全部质量数据表的元信息"""
    try:
        return {"tables": get_all_table_info()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ======================== 会话管理 ========================

@app.delete(
    "/agent/session/{session_id}",
    summary="清除会话",
    description="清除指定会话的对话历史。",
)
async def delete_session(session_id: str):
    """清除指定会话"""
    clear_session(session_id)
    return {"message": f"会话 {session_id} 已清除"}


# ======================== 预警告警接口 ========================

@app.get(
    "/agent/alerts",
    summary="查询质量预警",
    description="查询系统自动巡检产生的质量异常告警列表。",
)
async def list_alerts(level: str = None, limit: int = 50):
    """返回当前未确认的告警列表"""
    alerts = get_alerts(level=level, limit=limit)
    summary = get_alert_summary()
    return {"summary": summary, "alerts": alerts}


@app.post(
    "/agent/alerts/{alert_id}/ack",
    summary="确认告警",
    description="确认（消除）一条告警，表示已知悉或已处理。",
)
async def ack_alert(alert_id: int):
    """确认一条告警"""
    if acknowledge_alert(alert_id):
        return {"message": f"告警 {alert_id} 已确认"}
    raise HTTPException(status_code=404, detail=f"告警 {alert_id} 不存在")


@app.post(
    "/agent/alerts/check",
    summary="立即巡检",
    description="立即触发一次质量巡检，不等待定时器。",
)
async def trigger_check():
    """立即执行一次巡检"""
    run_all_checks()
    summary = get_alert_summary()
    return {"message": "巡检完成", "summary": summary}


# ======================== 用户画像接口 ========================

@app.get(
    "/agent/profile/{username}",
    summary="查询用户画像",
    description="获取指定用户的画像信息（角色、偏好、历史统计等）。",
)
async def get_user_profile(username: str):
    """查询用户画像"""
    profile = get_profile(username)
    return {"username": username, "profile": profile}


@app.put(
    "/agent/profile/{username}",
    summary="更新用户画像",
    description="手动设置用户画像（角色、部门、关注领域、详细程度等）。",
)
async def set_user_profile(username: str, raw_request: Request):
    """
    更新用户画像。请求体示例：
    {"role": "quality_engineer", "department": "品质部", "detail_level": "detailed"}
    """
    body = await raw_request.json()
    # 只允许更新的字段
    allowed = {"role", "department", "focus_areas", "detail_level", "notes"}
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        raise HTTPException(status_code=400, detail="没有可更新的字段")
    profile = update_profile(username, **fields)
    return {"username": username, "profile": profile}


# ======================== 启动入口 ========================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=API_CONFIG["host"],
        port=API_CONFIG["port"],
        reload=API_CONFIG["debug"],
    )
