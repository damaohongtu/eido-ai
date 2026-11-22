# Frontend static files must be built locally before building this image:
#   cd frontend && npm run build

ARG BASE_IMAGE=eido-base
FROM ${BASE_IMAGE}

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends nginx supervisor logrotate \
    && rm -rf /var/lib/apt/lists/*

COPY backend/ .

# Copy pre-built frontend static files
# Must be at /var/www/ai-eido/ so nginx root /var/www works correctly
COPY frontend/dist /var/www/ai-eido
COPY frontend/dist-mobile /var/www/h5/ai-eido

# nginx & supervisor config
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default
COPY docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Log rotation config
COPY docker/logrotate-eido.conf /etc/logrotate.d/eido
COPY docker/log-cron.sh /opt/log-cron.sh
RUN chmod +x /opt/log-cron.sh

# Create log directories
RUN mkdir -p /var/log/eido/app /var/log/eido/nginx

# Mount point for host .claude directory
RUN mkdir -p /workspace/.claude/skills

# Workspace paths — fixed for container layout
ENV WORKSPACE_ROOT=/workspace
ENV SKILLS_DIR=/workspace/.claude/skills
ENV LOG_DIR=/var/log/eido/app
ENV MPLCONFIGDIR=/tmp/matplotlib

EXPOSE 80

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
