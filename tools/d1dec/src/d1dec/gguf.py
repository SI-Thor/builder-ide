"""A small, self-contained GGUF reader.

Only what this server needs: the metadata, the tensor directory, and the
dequantisation of the two quantisations the d1 weights use (``F32`` and
``Q8_0``).

The layout follows the GGUF specification: a magic, a version, the tensor
and metadata counts, the metadata key/value pairs, the tensor directory,
padding to the file alignment, then the tensor data.
"""

from __future__ import annotations

import mmap
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np

GGUF_MAGIC = b"GGUF"

# metadata value types
(UINT8, INT8, UINT16, INT16, UINT32, INT32, FLOAT32, BOOL, STRING, ARRAY, UINT64, INT64, FLOAT64) = range(13)

# ggml tensor types used here
GGML_TYPE_F32 = 0
GGML_TYPE_F16 = 1
GGML_TYPE_Q8_0 = 8
GGML_TYPE_BF16 = 30

_SCALARS = {
    UINT8: ("<B", 1),
    INT8: ("<b", 1),
    UINT16: ("<H", 2),
    INT16: ("<h", 2),
    UINT32: ("<I", 4),
    INT32: ("<i", 4),
    FLOAT32: ("<f", 4),
    BOOL: ("<?", 1),
    UINT64: ("<Q", 8),
    INT64: ("<q", 8),
    FLOAT64: ("<d", 8),
}


@dataclass
class TensorInfo:
    name: str
    shape: tuple[int, ...]  # ggml order: shape[0] is the fastest dim
    dtype: int
    offset: int

    @property
    def n_elements(self) -> int:
        n = 1
        for d in self.shape:
            n *= d
        return n


class GGUFFile:
    """A memory-mapped GGUF file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._fh = open(self.path, "rb")
        # the file is mapped, not read: the model is 1.76 GB, and a
        # reader that copied it into the heap would raise the server's
        # peak memory by that much for nothing
        self._data = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        self._pos = 0
        self.meta: dict[str, Any] = {}
        self.tensors: dict[str, TensorInfo] = {}
        self._read_header()
        self._read_metadata()
        self._read_tensor_directory()
        align = int(self.meta.get("general.alignment", 32))
        self.data_offset = (self._pos + align - 1) // align * align

    # -- primitives ---------------------------------------------------------

    def _read(self, n: int) -> bytes:
        out = self._data[self._pos : self._pos + n]
        if len(out) != n:
            raise EOFError(f"{self.path}: truncated at {self._pos}")
        self._pos += n
        return out

    def _u32(self) -> int:
        return struct.unpack("<I", self._read(4))[0]

    def _u64(self) -> int:
        return struct.unpack("<Q", self._read(8))[0]

    def _string(self) -> str:
        n = self._u64()
        return self._read(n).decode("utf-8", errors="replace")

    # -- structure ----------------------------------------------------------

    def _read_header(self) -> None:
        if self._read(4) != GGUF_MAGIC:
            raise ValueError(f"{self.path}: not a GGUF file")
        self.version = self._u32()
        n_tensors = self._u64()
        n_kv = self._u64()
        self._n_tensors = n_tensors
        self._n_kv = n_kv

    def _read_value(self, vtype: int) -> Any:
        if vtype in _SCALARS:
            fmt, size = _SCALARS[vtype]
            return struct.unpack(fmt, self._read(size))[0]
        if vtype == STRING:
            return self._string()
        if vtype == ARRAY:
            elem_type = self._u32()
            count = self._u64()
            if elem_type == STRING:
                return [self._string() for _ in range(count)]
            if elem_type == ARRAY:
                raise ValueError("nested arrays are not supported")
            fmt, size = _SCALARS[elem_type]
            raw = self._read(size * count)
            arr = np.frombuffer(raw, dtype=np.dtype(fmt))
            if elem_type == BOOL:
                return arr.astype(bool).tolist()
            return arr.tolist()
        raise ValueError(f"unknown metadata value type {vtype}")

    def _read_metadata(self) -> None:
        for _ in range(self._n_kv):
            key = self._string()
            vtype = self._u32()
            self.meta[key] = self._read_value(vtype)

    def _read_tensor_directory(self) -> None:
        for _ in range(self._n_tensors):
            name = self._string()
            n_dims = self._u32()
            dims = tuple(self._u64() for _ in range(n_dims))
            dtype = self._u32()
            offset = self._u64()
            self.tensors[name] = TensorInfo(name, dims, dtype, offset)

    # -- access -------------------------------------------------------------

    def raw(self, name: str) -> np.ndarray:
        """The tensor's bytes, as a view into the file."""
        info = self.tensors[name]
        start = self.data_offset + info.offset
        return np.frombuffer(self._data, dtype=np.uint8, offset=start, count=_bytes_for(info))

    def get(self, name: str, dtype: np.dtype | type | None = None) -> np.ndarray:
        """The tensor as a numpy array, dequantised when needed.

        The result keeps ggml's shape order (``shape[0]`` is the fastest
        dim), so a weight ``[in, out]`` is used as ``x @ w``.

        ``dtype`` asks for the weights in another precision, which is
        what the engine wants: the dequantisation of a Q8_0 block into
        fp16 is the same rounding ggml does, so the model reads the
        weights in fp16 without ever holding an fp32 copy of them.
        """
        info = self.tensors[name]
        raw = self.raw(name)
        if info.dtype == GGML_TYPE_F32:
            arr = np.frombuffer(raw.tobytes(), dtype=np.float32)
            out = _to_ggml_order(arr, info.shape)
        elif info.dtype == GGML_TYPE_F16:
            arr = np.frombuffer(raw.tobytes(), dtype=np.float16)
            out = _to_ggml_order(arr, info.shape)
        elif info.dtype == GGML_TYPE_BF16:
            u16 = np.frombuffer(raw.tobytes(), dtype=np.uint16)
            arr = (u16.astype(np.uint32) << 16).view(np.float32)
            out = _to_ggml_order(arr, info.shape)
        elif info.dtype == GGML_TYPE_Q8_0:
            out = dequant_q8_0(raw, info.shape, dtype)
        else:
            raise ValueError(f"unsupported tensor type {info.dtype} for {name}")
        if dtype is not None:
            out = out.astype(dtype)
        return out

    def has(self, name: str) -> bool:
        return name in self.tensors

    def release(self) -> None:
        """Let the file go back to the box.

        The file is mapped, not copied, so there is nothing to give
        back in the heap — but the mapping is closed so that the pages
        are not held while the weights are on the GPU.
        """
        try:
            self._data.close()
        except Exception:
            pass
        try:
            self._fh.close()
        except Exception:
            pass

    def close(self) -> None:
        self.release()


def _bytes_for(info: TensorInfo) -> int:
    if info.dtype == GGML_TYPE_F32:
        return 4 * info.n_elements
    if info.dtype == GGML_TYPE_F16:
        return 2 * info.n_elements
    if info.dtype == GGML_TYPE_BF16:
        return 2 * info.n_elements
    if info.dtype == GGML_TYPE_Q8_0:
        # 32 elements per block: fp16 scale + 32 int8
        assert info.shape[0] % 32 == 0, info.shape
        return (info.shape[0] // 32) * 34 * info.n_elements // info.shape[0]
    raise ValueError(f"unsupported tensor type {info.dtype}")


def _to_ggml_order(flat: np.ndarray, shape: tuple[int, ...]) -> np.ndarray:
    """Put a flat buffer into ggml's axis order.

    ggml stores a tensor with its **first** dimension varying fastest,
    and the GGUF file keeps that order on disk. numpy's C order has the
    *last* dimension varying fastest, so the flat buffer is first read
    with the dimensions reversed and then transposed back.

    This is what gguf-py does (``np_dims = tuple(reversed(dims))`` before
    the reshape), and it is what llama.cpp's own loader assumes when it
    hands the bytes to ggml unchanged.
    """
    if len(shape) == 1:
        return flat.reshape(shape)
    return flat.reshape(shape[::-1]).transpose(*reversed(range(len(shape))))


def dequant_q8_0(
    raw: np.ndarray,
    shape: tuple[int, ...],
    dtype: np.dtype | type | None = None,
) -> np.ndarray:
    """Q8_0 -> float32 (or float16).

    A block is 32 values: one fp16 scale followed by 32 int8 codes. The
    scale multiplies the codes. The blocks run along the first (fastest)
    dimension, so the buffer is read row by row.

    With ``dtype=float16`` the block is multiplied in fp16, which is
    what ggml's own Q8_0 kernel does: the scale is already an fp16 and
    the codes are small integers, so the product is exact and the single
    rounding is the one ggml makes too.
    """
    n_cols = shape[0]
    n_rows = 1
    for d in shape[1:]:
        n_rows *= d
    n_blocks = n_cols // 32
    raw = raw[: n_blocks * 34 * n_rows].reshape(n_rows, n_blocks, 34)
    scales = raw[:, :, 0:2].copy().view(np.float16).reshape(n_rows, n_blocks, 1)
    codes = raw[:, :, 2:34].view(np.int8).reshape(n_rows, n_blocks, 32)
    if dtype is None:
        out = codes.astype(np.float32) * scales.astype(np.float32)
    else:
        out = codes.astype(dtype) * scales.astype(dtype)
    return _to_ggml_order(out.reshape(-1), shape)


def iter_arrays(f: GGUFFile, names: list[str]) -> Iterator[np.ndarray]:
    for n in names:
        yield f.get(n)
