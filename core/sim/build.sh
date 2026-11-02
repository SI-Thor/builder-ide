#!/usr/bin/env bash
# Build the batched simulator's Python module.
#
#   core/sim/build.sh
#
# Needs the repo's venv (pybind11) and the CUDA toolkit at
# /usr/local/cuda-13.2. The build has no CMAKE_BUILD_TYPE on purpose: no
# -DNDEBUG, so the device-side asserts stay in.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
BUILD="$REPO/build/sim"
CUDA_BIN="/usr/local/cuda-13.2/bin"
PYTHON="$REPO/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi

cmake -S "$HERE" -B "$BUILD" \
  -DCMAKE_CUDA_COMPILER="$CUDA_BIN/nvcc" \
  -DPython3_EXECUTABLE="$PYTHON" \
  -DCMAKE_BUILD_TYPE= \
  -DCMAKE_CUDA_ARCHITECTURES=110

cmake --build "$BUILD" -j "$(nproc)"
echo "built: $HERE/_pysim*.so"
