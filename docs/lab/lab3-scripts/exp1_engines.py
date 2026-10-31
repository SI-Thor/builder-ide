#!/usr/bin/env python3
"""EXP 1 -- What accelerators does this Thor actually expose to user software?

The brief asks for a fact check of Kimi's engine claims:
    "Hardware engines repurposed: NVDLA as a critic farm (does Thor even have
     NVDLA? Orin does), PVA as scheduler, NVENC/NVDEC to compress world-state
     latents between frames (warm start), CUDA Graphs to kill launch overhead."

and for "the power rails readable for a joules metric (INA sensors /
tegrastats VDD_* fields)".

Everything here is a *read*: no services touched, no system installs, nothing
written outside results/. Each check records the raw evidence so the verdict
can cite it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from boxstate import box_state, PowerSampler  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results")


def sh(cmd: list[str], timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"<error: {e}>"


# ------------------------------------------------------------------ /dev

def check_dev() -> dict:
    entries = sorted(os.listdir("/dev"))
    wanted = {
        "nvdla": [e for e in entries if "nvdla" in e.lower()],
        "pva": [e for e in entries if "pva" in e.lower()],
        "nvhost": [e for e in entries if "nvhost" in e.lower()],
        "nvenc": [e for e in entries if "nvenc" in e.lower()],
        "nvdec": [e for e in entries if "nvdec" in e.lower()],
        "ofa": [e for e in entries if "ofa" in e.lower()],
        "video_capture": [e for e in entries if e.startswith("video")],
        "jtag": [e for e in entries if "jtag" in e.lower()],
    }
    return {"total_entries": len(entries), "matches": wanted}


# ----------------------------------------------------------- device tree

def check_device_tree() -> dict:
    root = "/proc/device-tree"
    hits: dict[str, list[str]] = {}
    for key in ("nvdla", "pva", "ofa", "jtag", "coresight", "aon", "safety",
                "rtcpu", "nvhost", "host1x", "spe"):
        found = []
        for dirpath, dirnames, filenames in os.walk(root):
            for n in list(dirnames) + list(filenames):
                if key in n.lower():
                    found.append(os.path.join(dirpath, n).replace(root + "/", ""))
        hits[key] = sorted(found)[:25]
    # PVA context count from the DT node
    pva_ctx = 0
    pva_dir = os.path.join(root, "bus@0/host1x@8181200000/pva0@818c000000")
    if os.path.isdir(pva_dir):
        pva_ctx = len([n for n in os.listdir(pva_dir) if "_ctx" in n])
    return {"matches": hits, "pva_context_count": pva_ctx,
            "dtb": sh(["ls", "/boot/dtb/"]), "dtb_source": os.path.realpath(root)}


def dtb_strings() -> dict:
    """Search the compiled DTB for engine node names -- the DT in /proc can be
    filtered by the kernel, the DTB on disk is the full thing."""
    out = {}
    try:
        files = [os.path.join("/boot/dtb", f) for f in sorted(os.listdir("/boot/dtb"))]
    except Exception:
        return out
    for f in files:
        try:
            s = sh(["strings", f], timeout=60)
        except Exception:
            continue
        if not s or s.startswith("<error"):
            continue
        found = {}
        for key in ("nvdla", "pva", "ofa", "jtag", "coresight", "aon_cpu",
                    "safety", "rcpu", "nvhost"):
            toks = sorted({ln.strip() for ln in s.splitlines() if key in ln.lower()})
            found[key] = toks[:12]
        out[os.path.basename(f)] = found
    return out


# ------------------------------------------------------------- nvidia-smi

def check_nvidia_smi() -> dict:
    q = sh(["nvidia-smi", "-q"])
    def grab(pattern: str) -> list[str]:
        return [ln.strip() for ln in q.splitlines() if re.search(pattern, ln)]
    mem = grab(r"memory\.(total|used|free)")
    return {
        "name": grab(r"Product Name"),
        "arch": grab(r"Product Architecture"),
        "driver": grab(r"Driver Version"),
        "cuda": grab(r"^CUDA Version"),
        "pcie": grab(r"GPU Part Number|Board Part Number"),
        "engine_counters_present": {
            "Encoder": bool(grab(r"^\s*Encoder\s")),
            "Decoder": bool(grab(r"^\s*Decoder\s")),
            "JPEG": bool(grab(r"^\s*JPEG\s")),
            "OFA": bool(grab(r"^\s*OFA\s")),
        },
        "memory_reported": mem or ["(nvidia-smi reports no usable memory.total/used)"],
        "memory_is_na": all("N/A" in m for m in mem) if mem else True,
    }


# ---------------------------------------------------------------- power rails

def check_power_rails() -> dict:
    out = {"tegrastats_present": bool(sh(["which", "tegrastats"]))}
    with PowerSampler(interval_ms=250) as ps:
        import time
        time.sleep(1.5)
    out["sampled_rails"] = sorted({r for s in ps.samples for r in s.get("rails_mw", {})})
    out["report"] = ps.report()
    # INA / hwmon sensors exposed to user space
    ina = []
    for base in ("/sys/bus/i2c/drivers", "/sys/class/hwmon"):
        p = os.path.join(base)
        if os.path.isdir(p):
            for e in sorted(os.listdir(p)):
                if "ina" in e.lower():
                    ina.append(os.path.join(p, e))
    out["ina_sensors"] = ina
    out["hwmon_devices"] = sorted(os.listdir("/sys/class/hwmon")) if os.path.isdir("/sys/class/hwmon") else []
    return out


# ------------------------------------------------------- PVA / encoder reachability

def check_engine_reachability() -> dict:
    out = {}
    for node in ("/dev/nvhost-ctrl-pva0", "/dev/v4l2-nvenc", "/dev/v4l2-nvdec"):
        readable = os.access(node, os.R_OK | os.W_OK)
        out[node] = {"exists": os.path.exists(node), "rw": readable}
    out["ofa_device_nodes"] = [p for p in os.listdir("/dev") if "ofa" in p.lower()]
    out["devfreq"] = sorted(os.listdir("/sys/class/devfreq")) if os.path.isdir("/sys/class/devfreq") else []
    out["nvm_libraries"] = sorted(
        f for f in os.listdir("/usr/lib/aarch64-linux-gnu/nvidia") if "nvenc" in f or "nvdec" in f
    ) if os.path.isdir("/usr/lib/aarch64-linux-gnu/nvidia") else []
    out["media_controllers"] = sh(["media-ctl", "-p"])
    return out


# ---------------------------------------------------------------- jetpack

def check_jetpack() -> dict:
    rel = ""
    try:
        with open("/etc/nv_tegra_release") as f:
            rel = f.read().strip()
    except Exception:
        pass
    return {
        "nv_tegra_release": rel,
        "os_release": sh(["bash", "-lc", "grep -E '^(PRETTY_NAME|VERSION_ID)=' /etc/os-release"]),
        "kernel": sh(["uname", "-r"]),
        "cuda_version_nvidia_smi": sh(["bash", "-lc", "nvidia-smi | grep 'CUDA Version'"]),
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    result = {
        "box_state": box_state(),
        "dev": check_dev(),
        "device_tree": check_device_tree(),
        "dtb_strings": dtb_strings(),
        "nvidia_smi": check_nvidia_smi(),
        "power_rails": check_power_rails(),
        "engine_reachability": check_engine_reachability(),
        "jetpack": check_jetpack(),
    }
    path = os.path.join(OUT, "exp1_engines.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
