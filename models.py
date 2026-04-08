"""
质量管理 AI Agent 系统 - 数据模型定义
定义 API 请求/响应 和 Agent 内部通信的 Pydantic 模型。
"""
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ======================== 枚举类型 ========================

class AgentType(str, Enum):
    """子Agent类型"""
    SN_TRACE = "sn_trace"
    SUPPLIER = "supplier"
    SKU = "sku"
    FACTORY = "factory"
    MATERIAL = "material"
    ROOT_CAUSE = "root_cause"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ======================== API 请求模型 ========================

class ChatMessage(BaseModel):
    """单条对话消息"""
    role: MessageRole = MessageRole.USER
    content: str


class ChatRequest(BaseModel):
    """
    对话请求 - 与智能体管理平台对齐（参照OA agent协议）。
    平台通过 {"message": "用户问题"} 调用。
    """
    message: str = Field(..., description="用户的自然语言问题", examples=["SN12345的全链路质量数据是什么？"])
    session_id: Optional[str] = Field(None, description="会话ID，用于多轮对话上下文保持")


# ======================== API 响应模型 ========================

class ToolCallRecord(BaseModel):
    """工具调用记录，用于结果的可追溯性"""
    tool_name: str = Field(..., description="调用的工具名称")
    arguments: dict[str, Any] = Field(default_factory=dict, description="工具参数")
    result_summary: str = Field("", description="工具返回结果的摘要")


class AgentStep(BaseModel):
    """Agent执行步骤记录"""
    agent: str = Field(..., description="执行的Agent名称")
    action: str = Field(..., description="执行的动作描述")
    tool_calls: list[ToolCallRecord] = Field(default_factory=list, description="该步骤的工具调用记录")


class ChatResponse(BaseModel):
    """
    对话响应 - 与智能体管理平台对齐（参照OA agent协议）。
    核心字段 message 为Agent回答，其余为扩展字段。
    """
    message: str = Field(..., description="Agent的自然语言回答")
    session_id: Optional[str] = Field(None, description="会话ID")
    agent_used: Optional[str] = Field(None, description="最终处理请求的Agent")
    steps: list[AgentStep] = Field(default_factory=list, description="Agent执行步骤（可用于调试和审计）")
    data: Optional[list[dict[str, Any]]] = Field(None, description="查询返回的结构化数据（如有）")


class ErrorResponse(BaseModel):
    """错误响应"""
    error: str = Field(..., description="错误信息")
    detail: Optional[str] = Field(None, description="详细错误信息")


# ======================== Agent 注册信息模型 ========================

class AgentCapability(BaseModel):
    """Agent能力描述 - 用于向智能体管理平台注册"""
    name: str = Field(..., description="Agent名称")
    description: str = Field(..., description="Agent功能描述")
    supported_intents: list[str] = Field(default_factory=list, description="支持的意图类型")
    data_tables: list[str] = Field(default_factory=list, description="可访问的数据表")


class AgentRegistration(BaseModel):
    """
    Agent注册信息 - 向智能体管理平台注册时提供。
    """
    agent_id: str = Field("quality-agent", description="Agent唯一标识")
    name: str = Field("质量管理AI Agent", description="Agent名称")
    description: str = Field(
        "基于质量数据资产的智能分析Agent，支持SN溯源、供应商分析、SKU分析、"
        "代工厂分析、物料分析和根因分析等质量管理场景。",
        description="Agent整体描述",
    )
    version: str = Field("1.0.0", description="版本号")
    endpoint: str = Field(..., description="Agent服务的API地址")
    capabilities: list[AgentCapability] = Field(default_factory=list, description="子Agent能力列表")
    supported_features: list[str] = Field(
        default=["multi_turn_conversation", "structured_data_query", "quality_analysis", "root_cause_analysis"],
        description="支持的特性列表",
    )


# ======================== 健康检查模型 ========================

class HealthStatus(BaseModel):
    """健康检查状态"""
    status: str = Field("healthy", description="服务状态")
    version: str = Field("1.0.0")
    database: str = Field("unknown", description="数据库连接状态")
    llm: str = Field("unknown", description="LLM服务状态")
    timestamp: datetime = Field(default_factory=datetime.now)
