# The build of the batched simulator's Python module.
#
# The Thor's facts this file encodes:
#   - `nvcc` is not on PATH: it lives in /usr/local/cuda-13.2/bin.
#   - the GPU is sm_110 (Blackwell, compute capability 11.0).
#   - the build has **no** CMAKE_BUILD_TYPE, the way upstream Stratego's own
#     `make` does it: no -DNDEBUG, so the device-side asserts stay in and a
#     bad kernel says so instead of corrupting a number.
#   - pybind11 comes from the repo's own venv, not from the system.

cmake_minimum_required(VERSION 3.18)

if(NOT DEFINED CMAKE_CUDA_COMPILER)
  find_program(CMAKE_CUDA_COMPILER
    NAMES nvcc
    PATHS /usr/local/cuda-13.2/bin /usr/local/cuda/bin
    NO_DEFAULT_PATH)
  if(NOT CMAKE_CUDA_COMPILER)
    message(FATAL_ERROR "pysim: no CUDA compiler found; set CMAKE_CUDA_COMPILER")
  endif()
endif()

project(pysim LANGUAGES CXX CUDA)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CUDA_STANDARD 17)
set(CMAKE_CUDA_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

if(NOT CMAKE_CUDA_ARCHITECTURES)
  set(CMAKE_CUDA_ARCHITECTURES 110)
endif()

find_package(Python3 COMPONENTS Interpreter Development.Module REQUIRED)

# pybind11 lives in the venv: ask the interpreter where its cmake config is.
execute_process(
  COMMAND "${Python3_EXECUTABLE}" -m pybind11 --cmakedir
  OUTPUT_VARIABLE PYBIND11_CMAKE_DIR
  OUTPUT_STRIP_TRAILING_WHITESPACE
  RESULT_VARIABLE PYBIND11_RESULT)
if(NOT PYBIND11_RESULT EQUAL 0)
  message(FATAL_ERROR "pysim: pybind11 is not importable by ${Python3_EXECUTABLE}")
endif()
find_package(pybind11 CONFIG REQUIRED HINTS "${PYBIND11_CMAKE_DIR}")

get_filename_component(REPO_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../.." ABSOLUTE)

add_library(pysim MODULE
  bindings.cc
  registry.cc
  systems/register.cc
  systems/beacons/python.cpp
  systems/beacons/host.cc
  systems/beacons/kernels.cu)

target_include_directories(pysim PRIVATE "${REPO_ROOT}")
target_link_libraries(pysim PRIVATE pybind11::module)
target_compile_options(pysim PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-O2>)
target_compile_options(pysim PRIVATE
  $<$<COMPILE_LANGUAGE:CUDA>:--expt-relaxed-constexpr>)
set_target_properties(pysim PROPERTIES
  CUDA_SEPARABLE_COMPILATION OFF
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}")

# The module is imported as `core.sim._pysim`, so it is built next to the
# package.
set_target_properties(pysim PROPERTIES
  PREFIX ""
  OUTPUT_NAME "_pysim")
