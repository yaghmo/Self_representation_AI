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
# Weights and config are volume-mounted (docker-compose.yml's ./models,
# ./config) — those are per-instance, written by the cookbook. The
# llama-server binary itself is baked into the image below instead, since
# it's a fixed build artifact with no per-instance variation.

# ggml-org publishes no CUDA-enabled Linux release zip (only Windows CUDA
# zips and CPU/Vulkan/ROCm/SYCL Linux tarballs) — the Linux CUDA build only
# ships inside their server-cuda Docker image, so that's extracted from
# instead of a release download. CUDA 12 tag, matching torch's cu126 wheel
# ("12.x minors are binary compatible" — runtime/llamacpp.py's cuda_dll_dirs()).
FROM ghcr.io/ggml-org/llama.cpp:server-cuda AS llama-cuda

# trixie, not bookworm: the llama-server binary above (built on Ubuntu 24.04)
# needs GLIBC_2.38 / GLIBCXX_3.4.32 — bookworm's glibc 2.36 can't satisfy that.
FROM python:3.10-slim-trixie

# libsndfile1: soundfile (TTS wav encode) needs it at runtime on *both*
# images — voice synth is on the fan path too, /voice/speak has no agent gate.
# libgomp1: llama-server's Linux build links against it (OpenMP) — the
# Windows binary doesn't need an equivalent, it's statically linked in.
# docker-cli: runtime/qwentts.py's TTSServer shells out to `docker run` to
# launch qwentts.cpp's published image — Docker-outside-of-Docker, talking
# to the *host's* daemon over the socket docker-compose.yml mounts in. Only
# the client binary is ever used here, dockerd never runs inside this image
# — `docker.io` pulls in the daemon too and, on trixie, doesn't even ship
# the `docker` binary itself (that's `docker-cli`, a separate package).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsndfile1 \
        libgomp1 \
        ca-certificates \
        curl \
        docker-cli \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

ARG INSTALL_ADMIN=false

# compose builds cookbook/service-admin/web in parallel, sharing this cache
# mount — concurrent `uv sync` procs lock the same downloaded-wheel entry
# (e.g. nvidia-cudnn-cu12) and uv's default 300s wait can lose that race.
ENV UV_LOCK_TIMEOUT=1200

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

# Baked in after COPY . . so a stray host vendor/ in the build context (it's
# .dockerignored anyway) can never shadow it. The whole directory, not just
# the binary — llama-server dynamically links libggml*/libllama*/libmtmd
# .so files that ship alongside it. The upstream image resolves them via its
# own baked ldconfig cache, which we don't inherit (only /app's files were
# copied, not /etc/ld.so.cache), so LD_LIBRARY_PATH stands in for that.
COPY --from=llama-cuda /app/ /app/vendor/llama.cpp/bin/
RUN chmod +x /app/vendor/llama.cpp/bin/llama-server
ENV LD_LIBRARY_PATH="/app/vendor/llama.cpp/bin"

ENV PATH="/app/.venv/bin:$PATH"
RUN chmod +x docker/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8000"]
