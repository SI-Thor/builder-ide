#!/bin/bash
# Build the stratego CUDA extension on the Thor (CUDA 13.2, sm_110, aarch64).
#
#   bash build_thor.sh [checkout-dir]
#
# Defaults to ~/lm-wt/stratego/third_party/stratego. Assumes setup_env2.sh has
# already created <checkout>/.venv with torch 2.15.0+cu132.
set -euo pipefail

CHECKOUT="${1:-$HOME/lm-wt/stratego/third_party/stratego}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$CHECKOUT"

# The CMakeLists runs `python get_pybind_flags.py` and asks PyTorch for its
# paths, so the venv's python must be the `python` on PATH.
export PATH="$CHECKOUT/.venv/bin:$PATH"

# Apply the port (idempotent; prints what it changed).
python "$HERE/apply_port.py" "$CHECKOUT"

# sm_110 (Jetson Thor / GB10). Override with CMAKE_CUDA_ARCHITECTURES.
export CMAKE_CUDA_ARCHITECTURES="${CMAKE_CUDA_ARCHITECTURES:-110}"

# Upstream's `make` runs plain `cmake ..`, i.e. no CMAKE_BUILD_TYPE: no -DNDEBUG,
# so device asserts stay on and the per-step legality check stays in. We build
# the same way so the timing is comparable with upstream's A6000 numbers.
# Set BUILD_TYPE=Release to drop the asserts.
cmake -S . -B build \
    ${BUILD_TYPE:+-DCMAKE_BUILD_TYPE="$BUILD_TYPE"} \
    -DCMAKE_CUDA_ARCHITECTURES="${CMAKE_CUDA_ARCHITECTURES}" \
    -DCUDAToolkit_ROOT=/usr/local/cuda-13.2 \
    -DCMAKE_CUDA_COMPILER=/usr/local/cuda-13.2/bin/nvcc

cmake --build build -j "$(nproc)"

ls -l build/pystratego*.so
echo "BUILD_OK"
