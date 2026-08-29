# syntax=docker/dockerfile:1

# Two images from one Dockerfile — fan (default) and admin (INSTALL_ADMIN=true).
# See CLAUDE.md's "two surfaces" rule and pyproject.toml's `admin` extra:
# admin ships Scrapling + yt-dlp (a real headless Chromium) for social
# profile scraping; fan never calls those routes (_require_agent() gates
# them) so it never needs to carry that weight.
#
# GPU (both images): needs nvidia-container-toolkit on the host and
# `--gpus all` / a compose GPU reservation — torch's cu126 wheel already
# bundles the CUDA runtime, so no CUDA base image is needed.
#
# Weights, config, and the llama-server binary are all volume-mounted, not
# baked in — see docker-compose.yml's ./models, ./config, ./vendor mounts
# and docker/entrypoint.sh.

# trixie, not bookworm: the vendored linux llama-server binary (extracted from
# ggml-org's official CUDA image, itself built on Ubuntu 24.04) needs
# GLIBC_2.38 / GLIBCXX_3.4.32 — bookworm's glibc 2.36 can't satisfy that.
FROM python:3.10-slim-trixie

# libsndfile1: soundfile (TTS wav encode) needs it at runtime on *both*
# images — voice synth is on the fan path too, /voice/speak has no agent gate.
# libgomp1: llama-server's Linux build links against it (OpenMP) — the
# Windows binary doesn't need an equivalent, it's statically linked in.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 \
        libgomp1 \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

ARG INSTALL_ADMIN=false

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_ADMIN" = "true" ]; then \
        uv sync --frozen --extra runtime --extra admin; \
    else \
        uv sync --frozen --extra runtime; \
    fi

# Admin image only: Scrapling's real browser (Instagram/X/TikTok-search
# scraping — see runtime/og_scrape.py, x_scrape.py, handle_resolve.py)
# needs Chromium plus its system libs, not just the pip package.
RUN if [ "$INSTALL_ADMIN" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends \
            libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
            libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
            libgbm1 libasound2 libpango-1.0-0 libcairo2 \
        && rm -rf /var/lib/apt/lists/* \
        && /app/.venv/bin/scrapling install; \
    fi

COPY . .

ENV PATH="/app/.venv/bin:$PATH"
RUN chmod +x docker/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
