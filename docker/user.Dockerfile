# eido-user：每用户独立后端沙箱
#
# 与 app.Dockerfile 的差异：
# - 不打包前端静态资源
# - 不依赖 nginx / supervisor / logrotate
# - 不挂载 /var/log/eido/nginx
# - 入口直接 uvicorn，单进程；由 gateway 通过 docker SDK 编排
# - 默认环境 EIDO_TRUST_GATEWAY=1，让 backend/app/core/auth.py 接受 X-Eido-User-Id

ARG REGISTRY=docker.1ms.run
FROM ${REGISTRY}/python:3.12-slim

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        git \
        telnet \
        vim \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends \
        nodejs \
        fontconfig \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code --registry https://registry.npmmirror.com

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

COPY backend/ .

# /workspace 由 gateway 挂载只读 .claude/skills，/data 由 gateway 绑定独占 volume
RUN mkdir -p /workspace/.claude/skills /data /var/log/eido/app

ENV WORKSPACE_ROOT=/workspace
ENV SKILLS_DIR=/workspace/.claude/skills
ENV EIDO_DATA_ROOT=/data
ENV EIDO_TRUST_GATEWAY=1
ENV LOG_DIR=/var/log/eido/app
ENV PYTHONDONTWRITEBYTECODE=1

# 非 root 运行：volume 与 log 目录都让 eido 用户拥有
RUN useradd -r -u 10001 -m -s /usr/sbin/nologin eido \
    && chown -R eido:eido /app /workspace /data /var/log/eido

USER eido

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
