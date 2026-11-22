# Shared Python, Claude Code and document tooling.
ARG PYTHON_IMAGE=docker.1ms.run/python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG DEBIAN_MIRROR=https://mirrors.aliyun.com
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources

RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        curl \
        ca-certificates \
        fonts-dejavu-core \
        fonts-noto-cjk \
        libmagic1 \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt /tmp/eido-requirements.txt
RUN pip install --no-cache-dir -r /tmp/eido-requirements.txt \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --extra-index-url https://pypi.org/simple \
    --trusted-host mirrors.aliyun.com \
    && rm /tmp/eido-requirements.txt
# Expose the native CLI from the same SDK wheel used by ClaudeSDKClient.
RUN ln -sf "$(python -c 'import claude_agent_sdk,pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')" /usr/local/bin/claude \
    && claude --version
