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

exec "$@"
