# doubao-ask — Doubao Q&A (answer + citations) over HTTP, powered by opencli.
# Multi-arch base (arm64 devmac / amd64 Linux server); vinyard rebuilds from this file.
FROM node:20-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

# The vinyard server sits behind a slow international link: pull apt packages
# from TUNA (China mirror) instead of deb.debian.org. Harmless elsewhere.
RUN sed -i -e 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
           -e 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
           /etc/apt/sources.list.d/debian.sources

# Chromium + Xvfb (headed browser required by the opencli Browser Bridge
# extension), CJK fonts for Chinese pages, python for the API wrapper.
RUN apt-get update && apt-get install -y --no-install-recommends \
      chromium \
      xvfb \
      fonts-noto-cjk \
      python3 \
      python3-pip \
      python3-venv \
      curl \
      unzip \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# opencli CLI + Browser Bridge extension (pinned to the CLI's matching release).
ARG OPENCLI_VERSION=1.8.6
ARG EXTENSION_VERSION=1.0.22
RUN npm config set registry https://registry.npmmirror.com \
    && npm install -g "@jackwener/opencli@${OPENCLI_VERSION}" \
    && curl -fsSL -o /tmp/ext.zip \
       "https://github.com/jackwener/OpenCLI/releases/download/v${OPENCLI_VERSION}/opencli-extension-v${EXTENSION_VERSION}.zip" \
    && mkdir -p /opt/opencli-extension \
    && unzip -q /tmp/ext.zip -d /opt/opencli-extension \
    && rm /tmp/ext.zip \
    && ls /opt/opencli-extension/manifest.json

WORKDIR /app
COPY requirements.txt .
# Debian python is externally managed; a venv keeps pip installs clean.
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
ENV PATH="/opt/venv/bin:${PATH}"

COPY app.py entrypoint.sh ./
# Local opencli adapters (doubao incl. ask-cited) shadow the bundled ones.
COPY opencli-clis/ /root/.opencli/clis/
RUN chmod +x entrypoint.sh

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

CMD ["./entrypoint.sh"]
