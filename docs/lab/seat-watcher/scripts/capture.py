#!/usr/bin/env python3
"""Capture the raw sources for the seat-watcher experiment into raw/.

Everything the experiment reads is copied into raw/ first, so the reconstruction
and the scoring can be re-run from this directory alone (DOC-RULES rule 4).

Sources
  ProArt (this box)      ~/lm-ops/TEAM.md, ~/lm-ops/board-history/*.md,
                          ~/lm-ops/wt/*.out (seat outputs)
  Thor (ssh thor-lan)    ~/last-mile-ops.md, ~/lm-tools/thor-admit-daemon.log,
                          ~/.local/state/thor-admit/daemon.log, ~/lm-wt/*.out,
                          git history of every ~/lm-wt/*/.git worktree,
                          journalctl for the boot that hung and the boot after it

Nothing outside this directory is written. Reads elsewhere are read-only.

Usage:  python3 scripts/capture.py [--skip-ssh] [--jobs]
        (the live .out mtimes and the git history move with the day; re-running
         capture.py later will refresh them, which is why raw/ is not a fixture)
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW = os.path.join(ROOT, "raw")
THOR = "thor-lan"
THOR_BOOT_HANG = "ea0658fcb61f4ee784f5aaec840c45af"   # the boot that hung 10:49:53
THOR_BOOT_AFTER = "0336d5edd62d44fe891e1b9bf681874d"  # the boot after the power cycle
PROART_BOOT = "53937180e1834066a43da0be3e7b6c56"

SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", THOR]


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def sh_python(script, timeout=180):
    """Run a python script on the Thor.

    ssh concatenates its arguments and hands them to the remote shell, so a
    multi-line script would be mangled by the shell's quoting rules. Send it
    base64-encoded and pipe it into the remote interpreter instead.
    """
    import base64
    b64 = base64.b64encode(script.encode()).decode()
    r = sh(SSH + [f"echo {b64} | base64 -d | python3 -"], timeout=timeout)
    return r


def write(name, data, allow_empty=False):
    """Write a raw artefact.

    A failed ssh must never replace good captured data with an empty file, so
    an empty write is refused unless it is explicitly allowed.
    """
    path = os.path.join(RAW, name)
    if not data and not allow_empty and os.path.exists(path) and os.path.getsize(path) > 0:
        print(f"  -- raw/{name:44s} kept (new capture was empty)")
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        data = data.encode()
    with open(path, "wb") as fh:
        fh.write(data)
    print(f"  raw/{name:44s} {len(data):>10,} bytes")


ERR_CLASSES = [
    ("quota", ["usage limit reached", "limit exhausted", "(2056)"]),
    ("timeout", ["request timed out", "connect timeout error", "etimedout",
                 "connecttimeouterror", "econnreset", "socket hang up"]),
]


def classify(body):
    """Provider failures inside a seat transcript, by class and count."""
    low = body.lower()
    counts = {}
    for name, needles in ERR_CLASSES:
        n = sum(low.count(nd) for nd in needles)
        if n:
            counts[name] = n
    return counts


def capture_local():
    print("ProArt:")
    home = os.path.expanduser("~")
    for src, name in [
        (f"{home}/lm-ops/TEAM.md", "team.md"),
    ]:
        try:
            with open(src, "rb") as fh:
                write(name, fh.read())
        except OSError as exc:
            print(f"  !! {src}: {exc}")

    bd = f"{home}/lm-ops/board-history"
    if os.path.isdir(bd):
        for fn in sorted(os.listdir(bd)):
            if not fn.endswith(".md"):
                continue
            with open(os.path.join(bd, fn), "rb") as fh:
                write(f"board-history/{fn}", fh.read())
    else:
        print(f"  !! missing {bd}")

    # this box's journal for the day: it is where a *ProArt-side* API failure
    # would show up. Trimmed to 2026-11-01 because the boot runs from Oct 30.
    r = sh(["journalctl", "-b", PROART_BOOT, "--since", "2026-11-01 00:00:00",
            "--no-pager", "-o", "short-iso"])
    if r.returncode == 0 and r.stdout:
        write("proart-journal.log", r.stdout)

    # seat outputs: name, mtime (epoch), size, provider failures
    out = []
    wt = f"{home}/lm-ops/wt"
    if os.path.isdir(wt):
        for fn in sorted(os.listdir(wt)):
            if not fn.endswith(".out"):
                continue
            p = os.path.join(wt, fn)
            st = os.stat(p)
            with open(p, "rb") as fh:
                body = fh.read()
            lines = body.decode("utf-8", "replace").strip().splitlines()
            out.append({
                "seat": fn[:-4], "host": "proart", "path": p,
                "mtime": int(st.st_mtime), "size": st.st_size,
                "last_line": lines[-1][:200] if lines else "",
                "errors": classify(body.decode("utf-8", "replace")),
            })
    write("seats-proart.jsonl", "\n".join(json.dumps(r) for r in out))

    # local git history for the worktrees that live on this box
    rows = []
    for root, dirs, _ in os.walk(f"{home}/lm-wt", topdown=True):
        if ".git" in dirs:
            dirs[:] = [d for d in dirs if d != ".git"]
            rel = os.path.relpath(root, f"{home}/lm-wt")
            try:
                res = subprocess.run(["git", "-C", root, "log", "--all", "--format=%H%x09%ct"],
                                     capture_output=True, text=True, timeout=120)
            except Exception:
                continue
            for line in res.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) == 2:
                    rows.append({"repo": rel, "sha": parts[0], "ct": int(parts[1])})
    write("git-commits-proart.jsonl", "\n".join(json.dumps(x) for x in rows))
    return out


def capture_thor(skip_ssh=False):
    if skip_ssh:
        print("Thor: skipped")
        return []
    print("Thor:")
    r = sh(SSH + ["cat ~/last-mile-ops.md"])
    if r.returncode == 0:
        write("thor-last-mile-ops.md", r.stdout)
    else:
        print(f"  !! last-mile-ops.md: {r.stderr.strip()[:200]}")

    for remote, name in [
        ("~/lm-tools/thor-admit-daemon.log", "thor-daemon-lm-tools.log"),
        ("~/.local/state/thor-admit/daemon.log", "thor-daemon-state.log"),
    ]:
        r = sh(SSH + [f"cat {remote}"])
        if r.returncode == 0:
            write(name, r.stdout)
        else:
            print(f"  !! {remote}: {r.stderr.strip()[:200]}")

    for boot, name in [(THOR_BOOT_HANG, "thor-journal-boot-pre-hang.log"),
                       (THOR_BOOT_AFTER, "thor-journal-boot-post-hang.log")]:
        r = sh(SSH + [f"journalctl -b {boot} --no-pager -o short-iso"])
        if r.returncode == 0:
            write(name, r.stdout)
        else:
            print(f"  !! journal {boot}: {r.stderr.strip()[:200]}")

    # seat outputs on the Thor
    script = r"""
import json, os, glob
ERRS=[('quota',['usage limit reached','limit exhausted','(2056)']),
      ('timeout',['request timed out','connect timeout error','etimedout',
                  'connecttimeouterror','econnreset','socket hang up'])]
def classify(b):
    low=b.lower(); out={}
    for name,needles in ERRS:
        n=sum(low.count(x) for x in needles)
        if n: out[name]=n
    return out
rows=[]
for p in sorted(glob.glob(os.path.expanduser('~/lm-wt/*.out'))):
    st=os.stat(p)
    body=open(p,'rb').read().decode('utf-8','replace')
    lines=body.strip().splitlines()
    rows.append({'seat':os.path.basename(p)[:-4],'host':'thor','path':p,
                 'mtime':int(st.st_mtime),'size':st.st_size,
                 'last_line':lines[-1][:200] if lines else '',
                 'errors':classify(body)})
print(json.dumps(rows))
"""
    r = sh_python(script)
    seats = []
    if r.returncode == 0:
        try:
            seats = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception as exc:  # pragma: no cover - diagnostic path
            print(f"  !! seat list: {exc} :: {r.stdout[-200:]} :: {r.stderr[-200:]}")
    write("seats-thor.jsonl", "\n".join(json.dumps(x) for x in seats))

    # git history of every worktree under ~/lm-wt (one repo per seat)
    gitscript = r"""
import json, os, subprocess, glob
rows=[]
for d in sorted(glob.glob(os.path.expanduser('~/lm-wt/*'))):
    if not os.path.isdir(os.path.join(d,'.git')): continue
    try:
        out=subprocess.run(['git','-C',d,'log','--all','--format=%H%x09%ct'],capture_output=True,text=True,timeout=120).stdout
    except Exception: continue
    for line in out.strip().splitlines():
        parts=line.split('\t')
        if len(parts)==2:
            rows.append({'repo':os.path.basename(d.rstrip('/')),'sha':parts[0],'ct':int(parts[1])})
print(json.dumps(rows))
"""
    r = sh_python(gitscript, timeout=600)
    commits = []
    if r.returncode == 0:
        try:
            commits = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception as exc:  # pragma: no cover
            print(f"  !! git history: {exc} :: {r.stderr[-200:]}")
    write("git-commits-thor.jsonl", "\n".join(json.dumps(x) for x in commits))
    return seats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ssh", action="store_true",
                    help="do not touch the Thor (use the already-captured raw/)")
    args = ap.parse_args()
    os.makedirs(RAW, exist_ok=True)
    capture_local()
    capture_thor(args.skip_ssh)
    print("done.")


if __name__ == "__main__":
    sys.exit(main())
