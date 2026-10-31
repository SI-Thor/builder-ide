#!/usr/bin/env bash
# lab5 — snapshot of the box's state, to sit beside every number (CLAUDE.md:
# "Measure, with the box's state beside every number").
# Read-only; every probe degrades to "n/a" rather than failing.
set -u
echo "date: $(date -Is 2>/dev/null || date)"
echo "host: $(hostname 2>/dev/null) kernel: $(uname -r) arch: $(uname -m)"
echo "uptime: $(uptime 2>/dev/null)"
echo "loadavg: $(cat /proc/loadavg 2>/dev/null)"
grep -E '^(MemTotal|MemAvailable|SwapFree)' /proc/meminfo 2>/dev/null | sed 's/^/meminfo /'
echo "platform_profile: $(cat /sys/firmware/acpi/platform_profile 2>/dev/null || echo n/a)"
nvpmodel -q 2>/dev/null | grep -E "power|mode" | head -3 || echo "nvpmodel: n/a (no root)"
nvidia-smi --query-gpu=utilization.gpu,clocks.sm,power.draw,temperature.gpu,memory.used --format=csv,noheader 2>/dev/null | sed 's/^/nvidia-smi: /' || echo "nvidia-smi: n/a"
# one ~2 s sample of the rails, if tegrastats is reachable without a tty
if command -v tegrastats >/dev/null 2>&1; then
  timeout 2 tegrastats --interval 1000 2>/dev/null | head -2 | sed 's/^/tegrastats: /' || true
fi
echo "top-procs: $(ps -eo pcpu,comm --sort=-pcpu 2>/dev/null | sed -n '2,4p' | tr '\n' '|' )"
