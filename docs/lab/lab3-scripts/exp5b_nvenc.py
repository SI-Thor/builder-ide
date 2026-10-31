#!/usr/bin/env python3
"""EXP 5b -- NVENC/NVDEC round trip of a float field: a warm-start store.

Kimi's claim (round 3 brief):
    "NVENC/NVDEC to compress world-state latents between frames (warm start)"

and the brief's experiment 5:
    "NVENC/NVDEC round-trip of a float field packed as video (error vs
     bitrate) as a warm-start store."

The shape of the question matters. A *single* float field packed as one video
frame is the worst case for a video codec: the codec's own machinery (DCT,
chroma, rate control) buys nothing that a plain image codec does not already
do, and the field has to be quantised into 8-bit luma to get in at all.

The interesting case is a *sequence*: the previous world state is one frame of
a slowly evolving field, and a video codec's inter-frame prediction is exactly
built for that. So this experiment measures a SEQUENCE of T world states, not
one frame, and compares the video path against the stores it would have to
beat:

    raw uint8 / raw 10-bit   the field, unencoded
    PNG (per frame)          round 2's measured store: 88% of the encoder, and
                             10-228x the critic's own forward pass
    H.264 / H.265 / AV1 (NVENC)   the hardware path

And it measures the thing that would make the video path worth having anyway:
whether the encoder, which lives on its own clock domain (gpu-nvd-0), slows
down the GPU's tensor work while it runs.

Implementation notes (this ffmpeg has no `scale` filter, so the pixel format
cannot be converted in ffmpeg -- it has to be produced in Python):

  * the field is packed into **NV12** by hand: the Y plane carries the field,
    and U and V are constant 128 because the field is grey;
  * the RGB -> YUV mapping uses the **limited range** (16-235) with BT.601's
    0.859 luma weight, which is what a real conversion does, so the round trip
    is measured in the units the codec actually carries;
  * the decoded Y is mapped back with the inverse, so the error is the error
    the *field* suffers, not the error in an intermediate colour space.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boxstate import (PowerMeter, format_box_state, box_state,  # noqa: E402
                      gpu_clock_mhz, warm_gpu)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "results")

HW = 512          # the field is HW x HW
FRAMES = 30       # a sequence of world states
BT601_LUMA = 0.859


# ------------------------------------------------------------------ field

def make_sequence(hw: int = HW, frames: int = FRAMES, seed: int = 5) -> np.ndarray:
    """A smooth, slowly evolving scalar field -- a stand-in world state.

    Returned as float32 in [0, 1] at shape (frames, hw, hw).
    """
    rng = np.random.default_rng(seed)
    yy, xx = np.meshgrid(np.linspace(0, 1, hw), np.linspace(0, 1, hw), indexing="ij")
    field = np.zeros((frames, hw, hw), dtype=np.float32)
    for f in range(frames):
        t = f / max(frames - 1, 1)
        v = (0.45 * np.sin(2 * np.pi * (1.5 * xx + 0.5 * t))
             + 0.30 * np.cos(2 * np.pi * (1.1 * yy - 0.3 * t))
             + 0.18 * np.sin(2 * np.pi * (2.0 * xx + 2.0 * yy + 0.2 * t))
             + 0.07 * rng.standard_normal((hw, hw)).astype(np.float32))
        field[f] = v
    lo, hi = float(field.min()), float(field.max())
    return (field - lo) / (hi - lo)


def field_to_nv12(field: np.ndarray) -> bytes:
    """Pack the field into NV12 frames, the way a camera would.

    Y = 16 + 219 * luma(field)  (limited range), U = V = 128 (the field is grey).
    """
    hw = field.shape[-1]
    luma = field * BT601_LUMA
    y = np.clip(np.rint(16.0 + 219.0 * luma), 0, 255).astype(np.uint8)
    u = np.full((hw // 2, hw // 2), 128, dtype=np.uint8)
    v = np.full((hw // 2, hw // 2), 128, dtype=np.uint8)
    out = bytearray()
    for f in range(y.shape[0]):
        out += y[f].tobytes()
        out += u.tobytes()
        out += v.tobytes()
    return bytes(out)


def nv12_to_field(raw: bytes, hw: int, frames: int) -> np.ndarray:
    """Unpack NV12 frames back into the field's own units."""
    fsz = hw * hw + 2 * (hw // 2) * (hw // 2)
    n = min(frames, len(raw) // fsz)
    arr = np.frombuffer(raw[:n * fsz], dtype=np.uint8).reshape(n, fsz)
    y = arr[:, : hw * hw].reshape(n, hw, hw).astype(np.float32)
    return np.clip((y - 16.0) / 219.0 / BT601_LUMA, 0.0, 1.0)


# ---------------------------------------------------------------- ffmpeg

def ffmpeg_bin() -> str:
    return shutil.which("ffmpeg") or "/usr/bin/ffmpeg"


CONTAINER = {"h264": ".mp4", "hevc": ".mp4", "av1": ".mkv"}


def encode(nv12: bytes, hw: int, codec: str, bitrate_k: int, nframes: int,
            preset: str = "p4") -> dict:
    """Encode a raw NV12 stream with the hardware encoder, to a temp file."""
    enc = {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"}[codec]
    tmp = tempfile_named(CONTAINER[codec])
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "nv12", "-s", f"{hw}x{hw}",
        "-i", "pipe:0",
        "-c:v", enc, "-preset", preset, "-b:v", f"{bitrate_k}k",
        "-frames:v", str(nframes), tmp,
    ]
    t0 = time.perf_counter()
    with PowerMeter() as pm:
        t0m = pm.mark()
        p = subprocess.run(cmd, input=nv12, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        t1m = pm.mark()
        wall = time.perf_counter() - t0
        j = pm.joules_between("VIN_total", t0m, t1m)
        j_bl = pm.joules_above_baseline("VIN_total", t0m, t1m)
        w = pm.watts_between("VIN_total", t0m, t1m)
    if p.returncode != 0:
        return {"ok": False, "error": p.stderr.decode()[:400], "cmd": " ".join(cmd)}
    size = os.path.getsize(tmp)
    return {"ok": True, "file": tmp, "bytes": size,
            "wall_s": wall, "joules": j, "joules_above_baseline": j_bl,
            "mean_w": w, "cmd": " ".join(cmd),
            "fps": nframes / wall if wall > 0 else 0.0}


def tempfile_named(suffix: str) -> str:
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.close()
    return tmp.name


def decode(path: str, hw: int, nframes: int) -> dict:
    """Decode back to raw NV12 bytes."""
    tmp = tempfile_named(".nv12")
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-i", path, "-f", "rawvideo", "-pix_fmt", "nv12",
           "-frames:v", str(nframes), tmp]
    t0 = time.perf_counter()
    with PowerMeter() as pm:
        t0m = pm.mark()
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        t1m = pm.mark()
        wall = time.perf_counter() - t0
        j = pm.joules_between("VIN_total", t0m, t1m)
        j_bl = pm.joules_above_baseline("VIN_total", t0m, t1m)
        w = pm.watts_between("VIN_total", t0m, t1m)
    if p.returncode != 0:
        return {"ok": False, "error": p.stderr.decode()[:400]}
    data = open(tmp, "rb").read()
    os.unlink(tmp)
    return {"ok": True, "data": data, "wall_s": wall, "joules": j,
            "joules_above_baseline": j_bl, "mean_w": w, "cmd": " ".join(cmd)}


def png_sequence(field: np.ndarray) -> dict:
    """The comparator: PNG per frame (round 2's measured store)."""
    from PIL import Image
    import io
    total = 0
    t0 = time.perf_counter()
    for f in range(field.shape[0]):
        u8 = np.clip(np.rint(field[f] * 255.0), 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(u8, mode="L").save(buf, format="PNG", compress_level=6)
        total += buf.tell()
    wall = time.perf_counter() - t0
    return {"bytes": total, "wall_s": wall}


def rmse_vs(field: np.ndarray, decoded: np.ndarray) -> dict:
    """Error of the decoded field against the original float field."""
    err = decoded - field
    mse = float((err ** 2).mean())
    peak = float(field.max())
    psnr = 10 * np.log10(peak ** 2 / mse) if mse > 0 else float("inf")
    return {"rmse": float(np.sqrt(mse)), "max_abs": float(np.abs(err).max()),
            "psnr_db": float(psnr),
            "rmse_pct_of_range": float(np.sqrt(mse)) * 100.0}


# ------------------------------------------------------------ concurrency

def gpu_contention(nv12: bytes, hw: int, nframes: int) -> dict:
    """Does the hardware encoder slow the GPU's tensor work?

    A matmul loop is timed alone, then again while an NVENC encode runs. If
    the video engine really is on its own clock domain, the two numbers match.
    """
    a = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)
    b = torch.randn(4096, 4096, device="cuda", dtype=torch.bfloat16)

    def loop(seconds: float = 1.2):
        t0 = time.perf_counter()
        n = 0
        while time.perf_counter() - t0 < seconds:
            c = a @ b
            n += 1
            if n % 10 == 0:
                torch.cuda.synchronize()
        torch.cuda.synchronize()
        return n

    def timed():
        s, e = torch.cuda.Event(True), torch.cuda.Event(True)
        s.record(); loop(); e.record()
        torch.cuda.synchronize()
        return s.elapsed_time(e)

    timed()
    solo = timed()

    tmp = tempfile_named(".mp4")
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "nv12", "-s", f"{hw}x{hw}",
           "-i", "pipe:0", "-c:v", "hevc_nvenc", "-preset", "p4",
           "-b:v", "2000k", "-frames:v", str(nframes), tmp]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    try:
        p.stdin.write(nv12)
        p.stdin.close()
    except Exception:
        pass
    with_during = timed()
    p.wait()
    os.unlink(tmp)
    del a, b
    torch.cuda.empty_cache()
    return {"matmul_ms_alone": solo, "matmul_ms_during_encode": with_during,
            "slowdown_pct": (with_during - solo) / solo * 100.0}


# ------------------------------------------------------------------ main

def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    torch.backends.cuda.matmul.allow_tf32 = False
    print("=" * 78)
    print("EXP 5b -- NVENC/NVDEC round trip of a float field (warm-start store)")
    print("=" * 78)
    st = box_state()
    print(format_box_state(st))
    w = warm_gpu(seconds=2.0)
    print(f"  gpu clock warmed: {w['clock_before_mhz']:.0f} -> {w['clock_after_mhz']:.0f} MHz")
    print(f"  ffmpeg: {ffmpeg_bin()}")

    field = make_sequence(HW, FRAMES)
    nv12 = field_to_nv12(field)
    print(f"\n  field: {FRAMES} frames of {HW}x{HW} in [0,1] "
          f"({field.nbytes/1024**2:.1f} MiB as float32), packed as NV12 "
          f"({len(nv12)/1024**2:.1f} MiB)")

    results = {"config": {"hw": HW, "frames": FRAMES,
                          "bt601_luma": BT601_LUMA},
               "runs": []}

    # ---- the uncompressed / lossless comparators
    raw_u8_bytes = FRAMES * HW * HW
    raw_u10_bytes = FRAMES * HW * HW * 2
    png = png_sequence(field)
    print(f"\n--- uncompressed / lossless comparators (whole sequence) ---")
    print(f"    raw uint8              {raw_u8_bytes/1024**2:8.2f} MiB")
    print(f"    raw 10-bit (u16)       {raw_u10_bytes/1024**2:8.2f} MiB")
    print(f"    raw float16            {raw_u10_bytes/1024**2:8.2f} MiB")
    print(f"    PNG per frame          {png['bytes']/1024**2:8.2f} MiB  "
          f"({png['wall_s']*1000:.0f} ms, lossless)")
    results["comparators"] = {
        "raw_uint8_bytes": raw_u8_bytes,
        "raw_uint10_bytes": raw_u10_bytes,
        "raw_float16_bytes": raw_u10_bytes,
        "png_bytes": png["bytes"], "png_wall_s": png["wall_s"],
    }

    # ---- the hardware video path
    print("\n--- NVENC encode + decode ---")
    for codec in ("h264", "hevc", "av1"):
        for bitrate_k in (200, 1000, 5000):
            enc = encode(nv12, HW, codec, bitrate_k, FRAMES)
            if not enc.get("ok"):
                print(f"    {codec:5s} @{bitrate_k:5d}k  FAILED: {enc.get('error','')[:150]}")
                continue
            dec = decode(enc["file"], HW, FRAMES)
            if not dec.get("ok"):
                print(f"    {codec:5s} @{bitrate_k:5d}k  DECODE FAILED: {dec.get('error','')[:150]}")
                os.unlink(enc["file"])
                continue
            recon = nv12_to_field(dec["data"], HW, FRAMES)
            n = recon.shape[0]
            err = rmse_vs(field[:n], recon)
            row = {
                "codec": codec, "bitrate_k": bitrate_k,
                "bytes": enc["bytes"],
                "bytes_per_frame": enc["bytes"] / FRAMES,
                "frames_decoded": n,
                "encode_wall_s": enc["wall_s"], "encode_fps": enc["fps"],
                "encode_joules": enc["joules"],
                "encode_joules_above_baseline": enc["joules_above_baseline"],
                "encode_mean_w": enc["mean_w"],
                "decode_wall_s": dec["wall_s"], "decode_joules": dec["joules"],
                "decode_joules_above_baseline": dec["joules_above_baseline"],
                "roundtrip_joules": enc["joules"] + dec["joules"],
                "roundtrip_joules_above_baseline":
                    enc["joules_above_baseline"] + dec["joules_above_baseline"],
                "rmse": err["rmse"], "max_abs": err["max_abs"],
                "psnr_db": err["psnr_db"],
                "rmse_pct_of_range": err["rmse_pct_of_range"],
                "bits_per_pixel": enc["bytes"] * 8 / (FRAMES * HW * HW),
                "compression_vs_raw_u8": raw_u8_bytes / enc["bytes"],
                "gpu_clock_mhz": gpu_clock_mhz(),
            }
            results["runs"].append(row)
            print(f"    {codec:5s} @{bitrate_k:5d}k  {enc['bytes']/1024:8.1f} KiB "
                  f"({row['bits_per_pixel']:5.2f} bpp, {row['compression_vs_raw_u8']:5.1f}x vs raw)  "
                  f"enc {enc['wall_s']*1000:6.0f} ms ({enc['fps']:6.1f} fps)  "
                  f"dec {dec['wall_s']*1000:6.0f} ms  "
                  f"RMSE {err['rmse']:.5f} ({err['rmse_pct_of_range']:.3f}% of range)  "
                  f"PSNR {err['psnr_db']:5.1f} dB  "
                  f"RT {row['roundtrip_joules_above_baseline']:6.2f} J above baseline")
            os.unlink(enc["file"])

    # ---- THE PAYOFF: does a video round trip still warm-start the loop?
    #
    # A warm start is only worth anything if the store that carries the
    # previous world state back is accurate enough that the equilibrium loop
    # still converges in a couple of iterations. EXP 4 put the equilibrium
    # tolerance at 2e-3; this asks how many iterations the loop needs when the
    # warm start has been through the codec.
    print("\n--- does the video round trip still warm-start the equilibrium loop? ---")
    import exp4_equilibrium as E4
    CH, HW4, ETA, TOL = 64, 512, 0.9, 2e-3
    critic = E4.Critic(CH, HW4)
    gen = torch.Generator(device="cuda").manual_seed(3)
    x_guess = torch.randn(CH, HW4, HW4, device="cuda", generator=gen) * 0.5
    _, x_star, _ = E4.run_loop(critic, x_guess, ETA, TOL, 4000)
    scale = float(x_star.abs().max())
    d = torch.randn(CH, HW4, HW4, device="cuda", generator=gen)
    d = d / d.abs().max() * (0.1 * scale)
    warm = x_star + d

    it_exact, _, _ = E4.run_loop(critic, warm, ETA, TOL, 400)
    cold_it, _, _ = E4.run_loop(critic, torch.randn(CH, HW4, HW4, device="cuda",
                                                    generator=gen) * 0.5, ETA, TOL, 400)
    store_arm = {"cold_iterations": cold_it, "warm_exact_iterations": it_exact,
                 "tol": TOL, "rows": []}
    print(f"    cold start: {cold_it} iterations;  exact warm start (10% off): {it_exact} iterations")

    # round-trip the warm field itself through each codec and re-run
    for codec in ("hevc",):
        for bitrate_k in (200, 1000, 5000):
            # the field as the codec would carry it: one 8-bit plane per frame
            f8 = np.clip(np.rint((warm[0].cpu().numpy() / scale) * 0.5 + 0.5) * 255.0,
                         0, 255).astype(np.uint8)
            seq = np.repeat(f8[None], 3, axis=0).astype(np.float32) / 255.0
            seq = seq * 2.0 - 1.0   # [-1,1]
            enc2 = encode(field_to_nv12(seq), HW4, codec, bitrate_k, 3)
            if not enc2.get("ok"):
                continue
            dec2 = decode(enc2["file"], HW4, 3)
            os.unlink(enc2["file"])
            if not dec2.get("ok"):
                continue
            rec = nv12_to_field(dec2["data"], HW4, 3)[0] * 2.0 - 1.0
            err = float(np.sqrt(((rec - seq[0]) ** 2).mean()))
            warm_v = torch.from_numpy(rec).to("cuda").float()[None].repeat(CH, 1, 1) * scale
            it_v, _, _ = E4.run_loop(critic, warm_v, ETA, TOL, 400)
            row = {"codec": codec, "bitrate_k": bitrate_k,
                   "field_rmse_after_roundtrip": err,
                   "iterations_after_roundtrip": it_v}
            store_arm["rows"].append(row)
            print(f"    {codec} @{bitrate_k:5d}k: the warm field comes back with "
                  f"RMSE {err:.4f}; the loop then needs {it_v} iterations "
                  f"(exact warm start: {it_exact}, cold: {cold_it})")
    results["warm_start_store"] = store_arm

    # ---- does the encoder steal the GPU?
    print("\n--- does NVENC slow the GPU's tensor work? ---")
    con = gpu_contention(nv12, HW, FRAMES)
    results["gpu_contention"] = con
    print(f"    4096^3 matmul loop alone:            {con['matmul_ms_alone']:8.1f} ms")
    print(f"    the same loop during an NVENC encode: {con['matmul_ms_during_encode']:8.1f} ms"
          f"   ({con['slowdown_pct']:+.1f}%)")

    with open(os.path.join(OUT, "exp5b_nvenc.json"), "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nwrote {OUT}/exp5b_nvenc.json")


if __name__ == "__main__":
    main()
