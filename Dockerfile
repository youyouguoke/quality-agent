# ================================
# 质量管理 AI Agent - Dockerfile
# ================================

# --- 基础镜像 ---
FROM python:3.12-slim AS base

# --- 构建阶段 ---
FROM base AS builder

WORKDIR /build

# 使用清华源安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --trusted-host pypi.tuna.tsinghua.edu.cn \
    -r requirements.txt

# --- 运行阶段 ---
FROM base AS runtime

LABEL maintainer="quality-team" \
      description="质量管理 AI Agent 服务" \
      version="1.0.0"

WORKDIR /app

# 从构建阶段复制已安装的依赖
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && mkdir -p /app/logs /app/skills \
    && chown -R appuser:appuser /app

# 复制应用代码
COPY --chown=appuser:appuser app.py config.py database.py agents.py tools.py models.py mcp_client.py skill_manager.py ./

# 复制 Skill 文件（初始技能定义）
COPY --chown=appuser:appuser skills/ ./skills/

# 切换到非 root 用户
USER appuser

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/agent/health', timeout=5)" || exit 1

# 启动服务
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
