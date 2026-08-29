#!/bin/sh
set -e

# llama-server is a separate release binary (see runtime/llamacpp.py), not a
# Python package — it dynamically links CUDA runtime libraries. torch's own
# cu126 wheel already bundles those same libraries as separate `nvidia-*`
# pip packages, so reuse them instead of requiring a full CUDA toolkit in
# the image — the same trick runtime/llamacpp.py's own comment describes
# for Windows PATH, done here for Linux's LD_LIBRARY_PATH.
cuda_lib_path=$(python -c "
import glob, os, sysconfig
site = sysconfig.get_paths()['purelib']
libs = glob.glob(os.path.join(site, 'nvidia', '*', 'lib'))
print(':'.join(libs))
" 2>/dev/null || true)
if [ -n "$cuda_lib_path" ]; then
    export LD_LIBRARY_PATH="$cuda_lib_path:${LD_LIBRARY_PATH:-}"
fi

# The llama-server binary itself is a manual, one-time host step (its
# release zip is platform/CUDA-version specific — see runtime/llamacpp.py's
# own --setup message) and lives in the mounted vendor/ volume, not the
# image. Warn clearly rather than let the first chat request fail with a
# confusing error.
if ! python -m runtime.llamacpp --setup >/tmp/llamacpp_setup.log 2>&1; then
    echo "=================================================================="
    echo "  llama-server not found in vendor/llama.cpp/ (mounted volume)."
    echo "  Download the linux CUDA release zip from"
    echo "  https://github.com/ggml-org/llama.cpp/releases into vendor/llama.cpp/"
    echo "  on the host, then restart this container. The API will still"
    echo "  come up, but any chat request will fail until that's done."
    echo "=================================================================="
fi

exec "$@"
