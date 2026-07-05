# Playwright-python image ships Chromium + system fonts + zh-CN locale.
# CRITICAL: this tag's minor MUST equal the `playwright` pin in pyproject.toml —
# the browser binaries are versioned per playwright release, so a pip package
# ahead of the image (e.g. pip 1.61 on a v1.60 image) fails with "Executable
# doesn't exist". Bump BOTH together (base tag + pyproject pin).
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

# TZ must be set so the `schedule` library interprets HH:MM as Asia/Shanghai,
# not UTC.
ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install python deps first to leverage layer caching.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install -e .

# Persistent state lives here — mount as a named volume (compose) or PVC (k8s)
# so the per-account localStorage snapshots and logs survive container rebuilds.
RUN mkdir -p /app/data/auth /app/data/logs /app/data/artifacts \
    && chown -R pwuser:pwuser /app

USER pwuser

# Default: the long-running daily scheduler (all accounts).
CMD ["mteam-cli", "schedule"]
