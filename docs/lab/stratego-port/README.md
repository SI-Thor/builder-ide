# `stratego-port` — the Thor port of AtaraxosAI/stratego

Upstream [AtaraxosAI/stratego](https://github.com/AtaraxosAI/stratego) (MIT)
builds on **CUDA 11.8 / x86_64 / PyTorch 2.5.1**. The Thor has **CUDA 13.2**,
an **sm_110** GPU (Jetson AGX Thor / GB10) on **aarch64**, and **PyTorch
2.15.0+cu132**. This directory holds the recipe that bridges the two, and the
test run that gates it.

The upstream checkout lives in `third_party/stratego/` and is **gitignored**:
the port is tracked, the upstream tree is not. Upstream commit: `92db29e`.

## Files

| file | what it is |
|---|---|
| `apply_port.py` | the seven edits, applied as exact string replacements |
| `build_thor.sh` | configure + build the extension on the Thor |
| `run_ctest.sh` | the upstream ctest suite (45 cases) — the port's correctness gate |
| `time_one_test.sh` | time one ctest case alone, to separate "the port is slow" from "the box is busy" |
| `ctest.log` | the log of the last full run |

## The seven changes

`apply_port.py` refuses to continue if an anchor string is missing, so it is
idempotent and loud: re-running it on an already-ported checkout prints
`skip (already applied)` for each change and changes nothing.

| # | file | change | why |
|---|---|---|---|
| 1 | `CMakeLists.txt` | ask PyTorch for `_GLIBCXX_USE_CXX11_ABI` instead of hardcoding `0` | upstream's hardcoded `0` matches PyTorch 2.5.1's old-ABI wheels; PyTorch 2.15 is CXX11-ABI, and a mismatch makes every `std::string` argument mismatch libtorch |
| 2 | `CMakeLists.txt` | locate the CUDA 13.2 toolkit explicitly; target `sm_110` | `nvcc` is not on PATH on the Thor, and CUDA 13 dropped the `sm_52`/`sm_70` targets nvcc used to default to, so the architecture must be stated |
| 3 | `CMakeLists.txt` | `CUDNN_ROOT` points at the cuDNN bundled in the PyTorch wheel | there is no system cuDNN on the Thor |
| 4 | `get_pybind_flags.py` | tolerate PyTorch >= 2.6, which removed the `_PYBIND11_*` attributes | the crash left `PYBIND_FLAGS` empty, which then aborted the configure |
| 5 | `CMakeLists.txt` | quote the arguments of the `message()` calls | an empty value must not abort cmake ("message called with incorrect number of arguments") |
| 6 | `CMakeLists.txt` | C++20 for both the host compiler and nvcc | PyTorch >= 2.6 refuses anything older (`#error C++20 or later compatible compiler is required`) |
| 7 | `CMakeLists.txt` | restore `--expt-relaxed-constexpr` for nvcc | upstream wipes Torch's CUDA flags, and PyTorch 2.15's bundled CUB calls `constexpr __host__` functions from device code |

## How to run it

Needs a checkout at `~/lm-wt/stratego/third_party/stratego` with its own
`.venv` (torch 2.15.0+cu132) on PATH — `setup_env2.sh` in the upstream tree
creates it.

```bash
# 1. build (applies the port, then configures and compiles)
bash docs/lab/stratego-port/build_thor.sh
#    -> build/pystratego.cpython-312-aarch64-linux-gnu.so, ~10.9 MB, sm_110 code

# 2. the correctness gate: 45 upstream ctest cases over the rules engine
bash docs/lab/stratego-port/run_ctest.sh
#    -> ctest.log; the log ends with "CTEST_EXIT=<code>"

# 3. time one case alone (only when the box is busy and the suite is slow)
bash docs/lab/stratego-port/time_one_test.sh test_cemetery
```

`build_thor.sh` deliberately builds with **no** `CMAKE_BUILD_TYPE`, the way
upstream's `make` does: no `-DNDEBUG`, so the device-side asserts and the
per-step legality check stay in, and the timing is comparable with upstream's
own numbers. Set `BUILD_TYPE=Release` to drop them.

## How long it takes

- **Build:** ~10 min on the Thor (14 Neoverse cores), from a clean `build/`.
  Re-running `apply_port.py` over an already-ported checkout adds ~1 s.
- **ctest:** ~30 min wall clock with `-j 4`. The suite is CPU-heavy Python
  (it drives the rules engine from Python) and the four slowest cases each
  take minutes, not seconds.

## What this does not do

- It does not vendor or modify the upstream tree; the port is a patch recipe
  applied to a fresh clone.
- It does not change the build type away from upstream's default, so timings
  include upstream's debug asserts. A release build would be faster to run and
  is not what upstream's 10-20 s figure was measured with.
