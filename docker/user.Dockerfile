# eido-user：每用户独立后端沙箱
#
# 与 app.Dockerfile 的差异：
# - 不打包前端静态资源
# - 不依赖 nginx / supervisor / logrotate
# - 不挂载 /var/log/eido/nginx
# - 入口 tini + uvicorn，单进程；由 gateway 编排（docker SDK 或 K8s API）
# - 默认环境 EIDO_TRUST_GATEWAY=1，让 backend/app/core/auth.py 接受 X-Eido-User-Id
#
# tini 作为 PID 1：docker 模式下等价 --init；K8s 无 --init 等价物，
# Claude CLI 子进程退出后的僵尸进程必须由 init 进程回收

ARG BASE_IMAGE=eido-base
FROM ${BASE_IMAGE}

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends git telnet vim tini \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

# /workspace 由 gateway 挂载只读 .claude/skills，/data 由 gateway 绑定独占 volume
RUN mkdir -p /workspace/.claude/skills /data/home /data/cache /data/logs /var/log/eido/app

ENV WORKSPACE_ROOT=/workspace
ENV SKILLS_DIR=/workspace/.claude/skills
ENV EIDO_DATA_ROOT=/data
ENV EIDO_TRUST_GATEWAY=1
ENV LOG_DIR=/data/logs
ENV HOME=/data/home
ENV XDG_CACHE_HOME=/data/cache
ENV PYTHONDONTWRITEBYTECODE=1
ENV MPLCONFIGDIR=/tmp/matplotlib

# 非 root 运行：volume 与 log 目录都让 eido 用户拥有
RUN groupadd -g 10001 eido \
    && useradd -r -u 10001 -g 10001 -m -s /usr/sbin/nologin eido \
    && chown -R eido:eido /app /workspace /data /var/log/eido

USER eido

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
