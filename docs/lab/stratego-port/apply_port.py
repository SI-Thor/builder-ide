#!/usr/bin/env python3
"""Apply the Thor (CUDA 13.2 / sm_110 / aarch64) port to a checkout of
AtaraxosAI/stratego.

Upstream builds with CUDA 11.8 on x86_64 against PyTorch 2.5.1. The Thor has
CUDA 13.2, an sm_110 (Jetson Thor / GB10) GPU on aarch64, and PyTorch 2.15.0+cu132.
Each edit is listed in CHANGES below and applied as an exact string replacement;
a missing anchor is a hard error, so the script is idempotent and loud.

Usage:  python apply_port.py <path-to-stratego-checkout>
"""

import sys
from pathlib import Path

CHANGES: list[tuple[str, str, str, str]] = []


def change(path: str, old: str, new: str, why: str) -> None:
    CHANGES.append((path, old, new, why))


# --- 1. CMakeLists.txt: the C++ ABI must match the installed PyTorch. ---------
# Upstream hardcodes -D_GLIBCXX_USE_CXX11_ABI=0, which matches PyTorch 2.5.1's
# old-ABI wheels. PyTorch 2.15 ships CXX11-ABI=1 wheels, so the hardcoded 0
# makes every std::string argument mismatch libtorch and the extension fails to
# load. Ask PyTorch instead of guessing.
change(
    "CMakeLists.txt",
    """add_definitions(-D_GLIBCXX_USE_CXX11_ABI=0)""",
    """# The libstdc++ ABI must match the installed PyTorch exactly.
# Upstream hardcoded 0 (PyTorch 2.5.1, old ABI); PyTorch >= 2.7 wheels use the
# CXX11 ABI (1). Ask PyTorch rather than guessing.
execute_process(
  COMMAND python -c "import torch; print(int(torch._C._GLIBCXX_USE_CXX11_ABI))"
  OUTPUT_VARIABLE TORCH_CXX11_ABI
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
message("PyTorch CXX11 ABI: ${TORCH_CXX11_ABI}")
add_definitions(-D_GLIBCXX_USE_CXX11_ABI=${TORCH_CXX11_ABI})""",
    "libstdc++ ABI now follows the installed PyTorch instead of a hardcoded 0",
)

# --- 2. CMakeLists.txt: point at the CUDA 13.2 toolkit and build for sm_110. --
# `nvcc` is not on PATH on the Thor and CUDA 13 dropped sm_52/sm_70 (nvcc's
# default target), so the arch must be stated explicitly.
change(
    "CMakeLists.txt",
    """cmake_minimum_required(VERSION 3.25)
set(USE_CUDNN 1)""",
    """cmake_minimum_required(VERSION 3.25)
set(USE_CUDNN 1)

# Thor port: CUDA 13.2 toolkit (not on PATH) and sm_110 (Jetson Thor, GB10).
# CUDA 13 removed sm_52/sm_70, which nvcc used to target by default, so the
# architecture has to be stated. Override with -DCMAKE_CUDA_ARCHITECTURES=...
set(CMAKE_CUDA_ARCHITECTURES "110" CACHE STRING "CUDA architectures to build")
if(NOT DEFINED CUDAToolkit_ROOT OR CUDAToolkit_ROOT STREQUAL "")
  if(EXISTS "/usr/local/cuda-13.2")
    set(CUDAToolkit_ROOT "/usr/local/cuda-13.2")
  endif()
endif()
if(EXISTS "${CUDAToolkit_ROOT}/bin/nvcc")
  set(CMAKE_CUDA_COMPILER "${CUDAToolkit_ROOT}/bin/nvcc")
endif()""",
    "CUDA 13.2 toolkit located explicitly; target arch set to sm_110",
)

# --- 3. CMakeLists.txt: cuDNN lives in the venv, not in /usr. ----------------
# The PyTorch wheel ships nvidia-cudnn-cu13 inside site-packages; Torch's cmake
# looks for cuDNN under CUDNN_ROOT.
change(
    "CMakeLists.txt",
    """# find Pytorch
execute_process(
  COMMAND python -c "import torch; import os; print(os.path.dirname(torch.__file__), end='')"
  OUTPUT_VARIABLE TorchPath
)""",
    """# find Pytorch
execute_process(
  COMMAND python -c "import torch; import os; print(os.path.dirname(torch.__file__), end='')"
  OUTPUT_VARIABLE TorchPath
)
# The PyTorch wheel ships cuDNN inside site-packages/nvidia/cudnn; point
# CUDNN_ROOT at it so Torch's cmake finds it.
execute_process(
  COMMAND python -c "import torch, os; p=os.path.join(os.path.dirname(torch.__file__), '..', 'nvidia', 'cudnn', 'include'); print(os.path.abspath(p) if os.path.isdir(p) else '', end='')"
  OUTPUT_VARIABLE TORCH_CUDNN_INCLUDE
  OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(TORCH_CUDNN_INCLUDE)
  set(CUDNN_ROOT "${TORCH_CUDNN_INCLUDE}/..")
  message("cuDNN root: ${CUDNN_ROOT}")
endif()""",
    "cuDNN_ROOT points at the wheel's bundled cuDNN",
)


# --- 4. get_pybind_flags.py: torch >= 2.6 no longer exposes _PYBIND11_* -----
# Upstream's script does `getattr(torch._C, f"_PYBIND11_{name}")` with no
# default, so on PyTorch 2.15 it raises AttributeError, the script exits
# non-zero, PYBIND_FLAGS comes out empty, and `message(${PYBIND_FLAGS})` then
# aborts the configure with "message called with incorrect number of
# arguments". The attributes were removed in PyTorch 2.6.
#
# The flags tell pybind11 which compiler/stdlib/ABI string to bake into its
# internals ID, so that our extension and libtorch share one type registry.
# pybind11 2.14 (the pinned submodule) derives exactly those values from the
# compiler when the macros are undefined -- and we now compile with the same
# _GLIBCXX_USE_CXX11_ABI as the installed torch -- so on a modern torch the
# right thing is to let pybind11 auto-detect and emit nothing.
change(
    "get_pybind_flags.py",
    """import torch._C

cmake_cxx_flags = []
for name in ["COMPILER_TYPE", "STDLIB", "BUILD_ABI"]:
    val = getattr(torch._C, f"_PYBIND11_{name}")
    if val is not None:
        cmake_cxx_flags += [rf"-DPYBIND11_{name}=\\"{val}\\""]
print(" ".join(cmake_cxx_flags), end="")""",
    """import torch._C

cmake_cxx_flags = []
for name in ["COMPILER_TYPE", "STDLIB", "BUILD_ABI"]:
    # PyTorch >= 2.6 removed the _PYBIND11_* attributes. pybind11 >= 2.11
    # derives the same values from the compiler, and we compile with the same
    # _GLIBCXX_USE_CXX11_ABI as the installed torch, so the auto-detected
    # internals ID matches libtorch's. Emit nothing when torch does not tell
    # us; emitting a guessed string would be worse than none.
    val = getattr(torch._C, f"_PYBIND11_{name}", None)
    if val is not None:
        cmake_cxx_flags += [rf"-DPYBIND11_{name}=\\"{val}\\""]
print(" ".join(cmake_cxx_flags), end="")""",
    "get_pybind_flags.py tolerates torch >= 2.6, which dropped _PYBIND11_*",
)

# --- 5. CMakeLists.txt: message() with an empty/unquoted variable aborts ----
# `message(${VAR})` with an empty VAR calls message() with zero arguments, and
# with a list-valued VAR it calls it with a list: both are CMake errors.
change(
    "CMakeLists.txt",
    """message(${TorchPath})
message(${PYBIND_FLAGS})
message(${CMAKE_CXX_FLAGS})
message(${TORCH_INCLUDE_DIRS})""",
    """message("${TorchPath}")
message("${PYBIND_FLAGS}")
message("${CMAKE_CXX_FLAGS}")
message("${TORCH_INCLUDE_DIRS}")""",
    "message() calls quote their argument so an empty value cannot abort cmake",
)


# --- 6. CMakeLists.txt: PyTorch 2.15 requires C++20. -------------------------
# Upstream pins C++17 for PyTorch 2.5.1. PyTorch >= 2.6 refuses to compile
# with anything older: torch/all.h has `#error C++20 or later compatible
# compiler is required to use PyTorch`.
change(
    "CMakeLists.txt",
    """set(CMAKE_CXX_STANDARD 17)""",
    """# PyTorch >= 2.6 requires a C++20 compiler (torch/all.h has an #error for
# anything older). Upstream pinned C++17 for PyTorch 2.5.1.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CUDA_STANDARD 20)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)""",
    "C++20 for both the host compiler and nvcc, as PyTorch 2.15 requires",
)


# --- 7. CMakeLists.txt: keep --expt-relaxed-constexpr for nvcc. -------------
# The line above deliberately wipes Torch's CUDA flags ("Caffe2 destroys any
# sane modern cmake CUDA setup"). With PyTorch 2.5.1 + CUDA 11.8 that was
# survivable; PyTorch 2.15 ships a CUB whose device-side reductions call
# constexpr __host__ functions, which nvcc rejects without this flag.
change(
    "CMakeLists.txt",
    """set(CMAKE_CUDA_FLAGS "${COMPILATION_FLAGS}")""",
    """set(CMAKE_CUDA_FLAGS "${COMPILATION_FLAGS}")
# PyTorch 2.15's bundled CUB calls constexpr __host__ functions from device
# code; nvcc rejects that unless --expt-relaxed-constexpr is given. The flag
# used to arrive through Torch's own CUDA flags, which the line above wipes.
set(CMAKE_CUDA_FLAGS "${CMAKE_CUDA_FLAGS} --expt-relaxed-constexpr")""",
    "--expt-relaxed-constexpr restored for nvcc (needed by PyTorch 2.15's CUB)",
)

# --- 8. pyengine/utils/helper.py: NVML does not exist on the Thor. -----------
# The trainer logs a GPU-memory counter every iteration (RL.log_stats,
# pyengine/core/rl.py:386 -> utils.get_gpumem_usage_gb()). That helper asks
# NVML for the device's used memory. On the Jetson Thor, NVML is not
# supported: nvidia-smi reports "Not Supported" for memory, and
# nvmlDeviceGetMemoryInfo raises NVMLError_NotSupported. The exception is not
# caught, so the *first* log_stats() after the first iteration kills the run -
# the training itself is fine, the counter is not.
#
# The fallback is this process's own reserved GPU memory. On the Thor that is
# the better number anyway: the GPU memory IS the system memory, so a
# device-wide "used" figure counts other seats' work as ours.
change(
    "pyengine/utils/helper.py",
    """def get_gpumem_usage_gb():
    handle = nvmlDeviceGetHandleByIndex(0)
    mem = nvmlDeviceGetMemoryInfo(handle)
    return mem.used / (2**30)""",
    """def get_gpumem_usage_gb():
    # Thor port: NVML is not supported on the Jetson Thor (nvidia-smi reports
    # "Not Supported" for memory), so nvmlDeviceGetMemoryInfo raises
    # NVMLError_NotSupported and takes the whole training run down at the first
    # log_stats(). Fall back to this process's own reserved GPU memory, which
    # is the meaningful number here anyway: on the Thor the GPU memory IS the
    # system memory, so NVML's device-wide "used" counts other seats' work.
    try:
        handle = nvmlDeviceGetHandleByIndex(0)
        mem = nvmlDeviceGetMemoryInfo(handle)
        return mem.used / (2**30)
    except Exception:
        return torch.cuda.memory_reserved() / (2**30)""",
    "the GPU-memory counter degrades gracefully when NVML is unsupported",
)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1]).resolve()
    if not (root / "CMakeLists.txt").is_file():
        print(f"not a stratego checkout: {root}")
        return 2

    for rel, old, new, why in CHANGES:
        path = root / rel
        text = path.read_text()
        if new in text:
            print(f"skip (already applied): {rel} -- {why}")
            continue
        if old not in text:
            print(f"ANCHOR NOT FOUND in {rel}: {old[:70]!r}")
            return 1
        path.write_text(text.replace(old, new, 1))
        print(f"patched {rel}: {why}")

    print(f"\n{len(CHANGES)} change(s) applied to {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
