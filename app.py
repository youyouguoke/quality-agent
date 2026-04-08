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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents import clear_session, run_master_agent
from config import API_CONFIG, LLM_CONFIG
from database import get_all_table_info, get_pool
from models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthStatus,
)

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
    yield
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
async def chat(request: ChatRequest):
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
    start_time = time.time()

    try:
        result = run_master_agent(
            query=request.message,
            session_id=request.session_id,
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


# ======================== 启动入口 ========================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=API_CONFIG["host"],
        port=API_CONFIG["port"],
        reload=API_CONFIG["debug"],
    )
