# Frontend static files must be built locally before building this image:
#   cd frontend && npm run build

# ARG REGISTRY allows overriding the base image registry
# Default uses a Chinese mirror; international: --build-arg REGISTRY=
ARG REGISTRY=docker.1ms.run
FROM ${REGISTRY}/python:3.12-slim

# Use Aliyun apt mirror for faster package downloads in China
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list 2>/dev/null || true

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        nginx \
        supervisor \
        logrotate \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install claude CLI via npmmirror (Taobao)
RUN npm install -g @anthropic-ai/claude-code --registry https://registry.npmmirror.com

# Install Python dependencies via Aliyun PyPI mirror
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com

# Copy backend source
COPY backend/ .

# Copy pre-built frontend static files
# Must be at /var/www/ai-eido/ so nginx root /var/www works correctly
COPY frontend/dist /var/www/ai-eido

# nginx & supervisor config
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Log rotation config
COPY docker/logrotate-eido.conf /etc/logrotate.d/eido
COPY docker/log-cron.sh /opt/log-cron.sh
RUN chmod +x /opt/log-cron.sh

# Create log directories
RUN mkdir -p /var/log/eido/app /var/log/eido/litellm /var/log/eido/nginx

# Mount point for host .claude directory
RUN mkdir -p /workspace/.claude/skills

# Workspace paths — fixed for container layout
ENV WORKSPACE_ROOT=/workspace
ENV SKILLS_DIR=/workspace/.claude/skills
ENV LOG_DIR=/var/log/eido/app

EXPOSE 80

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
