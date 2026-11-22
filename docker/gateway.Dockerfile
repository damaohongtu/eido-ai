# eido-gateway：CAS 鉴权 + 用户沙箱编排 + 反代
#
# 与 app.Dockerfile 的差异：
# - 不再随镜像启 user 业务进程；业务路由由 gateway 反代到 docker run 出来的
#   eido-user 容器
# - 仍然内置 nginx 用于静态前端 + /api 反代到本机 8000（gateway 进程）
# - 需要访问 docker daemon：运行时挂载 /var/run/docker.sock

ARG BASE_IMAGE=eido-base
FROM ${BASE_IMAGE}

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends nginx supervisor logrotate \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

COPY frontend/dist /var/www/ai-eido

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

COPY docker/logrotate-eido.conf /etc/logrotate.d/eido
COPY docker/log-cron.sh /opt/log-cron.sh
RUN chmod +x /opt/log-cron.sh

RUN mkdir -p /var/log/eido/app /var/log/eido/nginx

# /workspace 仅作为只读技能库 / sandbox registry / scheduled tasks 的承载点
RUN mkdir -p /workspace/.claude/skills

ENV WORKSPACE_ROOT=/workspace
ENV SKILLS_DIR=/workspace/.claude/skills
ENV LOG_DIR=/var/log/eido/app
ENV EIDO_SANDBOX_MODE=docker
ENV EIDO_USER_IMAGE=eido-user:latest
ENV EIDO_NET=eido-net
ENV MPLCONFIGDIR=/tmp/matplotlib

EXPOSE 80

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
