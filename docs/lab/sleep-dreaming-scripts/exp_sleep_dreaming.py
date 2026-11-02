#!/usr/bin/env python3
"""Toy continual learning with and without a sleep phase.

SLEEP = "Language Models Need Sleep" (arXiv:2606.03979, CC BY 4.0). This toy
keeps its four load-bearing parts: freeze what we know, write the new
knowledge into fresh parameters, distil on the model's own samples, prune the
transient. It is not the paper's experiment; docs/lab/exp-sleep-dreaming.md
says what was kept and what was dropped.

Task: two-phase class-incremental learning. Phase A learns classes 0-4, phase
B learns 5-9, through a shared trunk and a shared 10-way head. Learning B
overwrites the head rows that carry A's classes; that is the forgetting.

Arms (the same gradient-step budget in every arm):
  seq         wake A, wake B, stop.
  seq_extra   seq + T more steps on B (the compute-matched control).
  replay      seq + T steps replaying A's stored samples with true labels.
  sleep       wake A (all params), wake B (trunk + transient expert, head
              FROZEN), then T consolidation steps: prune the transient expert,
              add a fresh one, train only it on the TEACHER's own samples.
  sleep_dream sleep + T dreaming steps: the model generates its own samples, a
              gradient filter keeps the best, and they are trained on.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boxstate import box_state, format_box_state

D_IN, D_HID, N_CLS, RANK = 16, 32, 10, 8
A_CLS, B_CLS = (0, 5), (5, 10)
N_TRAIN, N_TEST, BATCH, LR, MOM = 600, 300, 64, 0.05, 0.9


class Expert(nn.Module):
    """A low-rank addition to the head — SLEEP's new capacity."""

    def __init__(self):
        super().__init__()
        self.A = nn.Parameter(torch.zeros(RANK, D_HID))
        self.B = nn.Parameter(torch.zeros(N_CLS, RANK))

    def delta(self):
        return self.B @ self.A


class Net(nn.Module):
    """trunk (plastic, shared) + head (the stable block) + expert slots."""

    def __init__(self, n_experts=0):
        super().__init__()
        self.trunk = nn.Linear(D_IN, D_HID)
        self.head = nn.Linear(D_HID, N_CLS)
        self.experts = nn.ModuleList([Expert() for _ in range(n_experts)])

    def forward(self, x):
        h = F.relu(self.trunk(x))
        w = self.head.weight
        for e in self.experts:
            w = w + e.delta()
        return F.linear(h, w, self.head.bias)


def make_task(classes, seed, n):
    """Gaussian clusters, one per class, with the class's global label."""
    gen = torch.Generator().manual_seed(seed)
    lo, hi = classes
    centers = torch.randn(hi - lo, D_IN, generator=gen) * 2.0
    y = torch.randint(0, hi - lo, (n,), generator=gen)
    return centers[y] + torch.randn(n, D_IN, generator=gen), y + lo


def train(model, params, x, y, steps, gen, lr=LR):
    if not params:
        return float("nan")
    opt = torch.optim.SGD(params, lr=lr, momentum=MOM)
    val = float("nan")
    for _ in range(steps):
        idx = torch.randint(0, x.shape[0], (BATCH,), generator=gen)
        loss = F.cross_entropy(model(x[idx]), y[idx])
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        val = float(loss.item())
    return val


def kd(student, teacher, temp=1.0):
    """KL(teacher || student) on the teacher's own distribution."""
    p = torch.log_softmax(teacher / temp, dim=-1)
    q = torch.log_softmax(student / temp, dim=-1)
    return (p.exp() * (p - q)).sum(-1).mean() * temp ** 2


@torch.no_grad()
def acc(model, x, y):
    return float((model(x).argmax(-1) == y).float().mean())


def consolidate(model, teacher, prompts, steps, gen, lam=0.5, temp=1.0):
    """SLEEP's consolidation: prune the transient expert, expand into a fresh
    one, and train nothing but the fresh one, on the teacher's own samples."""
    fresh = Expert()
    model.experts.append(fresh)
    opt = torch.optim.SGD([fresh.A, fresh.B], lr=LR, momentum=MOM)
    val = float("nan")
    for _ in range(steps):
        idx = torch.randint(0, prompts.shape[0], (BATCH,), generator=gen)
        xp = prompts[idx]
        with torch.no_grad():
            t = teacher(xp)
            y_hat = torch.multinomial(torch.softmax(t / temp, -1), 1).squeeze(1)
        s = model(xp)
        loss = (1 - lam) * kd(s, t, temp) + lam * F.cross_entropy(s, y_hat)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
        val = float(loss.item())
    return val


def dream(model, prompts, steps, gen, n_cand=64, keep=0.5, temp=1.0):
    """SLEEP's dreaming: generate, select by gradient, train.

    The model generates its own samples (labels sampled from its own
    predictive distribution); a gradient filter keeps the candidates with the
    largest gradient, and only those are trained on.
    """
    params = [p for p in model.parameters() if p.requires_grad]
    if not params:
        return float("nan")
    opt = torch.optim.SGD(params, lr=LR, momentum=MOM)
    val = float("nan")
    rounds = max(1, steps // 8)
    per = max(1, steps // rounds)
    for _ in range(rounds):
        idx = torch.randint(0, prompts.shape[0], (n_cand,), generator=gen)
        xc = prompts[idx]
        with torch.no_grad():
            y_hat = torch.multinomial(torch.softmax(model(xc) / temp, -1), 1).squeeze(1)
        scores = []
        for i in range(xc.shape[0]):
            loss = F.cross_entropy(model(xc[i : i + 1]), y_hat[i : i + 1])
            g = torch.autograd.grad(loss, params, allow_unused=True)
            scores.append(sum((x.pow(2).sum().item() for x in g if x is not None)) ** 0.5)
        keepn = max(1, int(keep * len(scores)))
        order = torch.argsort(torch.tensor(scores), descending=True)[:keepn]
        for _ in range(per):
            j = order[torch.randint(0, keepn, (1,), generator=gen)]
            loss = F.cross_entropy(model(xc[j : j + 1]), y_hat[j : j + 1])
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            val = float(loss.item())
    return val


def run(arm, seed, steps, T, dream_steps):
    torch.manual_seed(seed)
    data = {
        "A": {"train": make_task(A_CLS, seed * 1000 + 1, N_TRAIN),
              "test": make_task(A_CLS, seed * 1000 + 2, N_TEST)},
        "B": {"train": make_task(B_CLS, seed * 1000 + 3, N_TRAIN),
              "test": make_task(B_CLS, seed * 1000 + 4, N_TEST)},
    }
    xa, ya = data["A"]["train"]
    xb, yb = data["B"]["train"]
    t0 = time.perf_counter()
    model = Net()
    params = list(model.parameters())
    if arm in ("seq", "seq_extra"):
        gen = torch.Generator().manual_seed(seed + 101)
        train(model, params, xa, ya, steps, gen)
        a0 = acc(model, *data["A"]["test"])
        train(model, params, xb, yb, steps, gen)
        if arm == "seq_extra":
            train(model, params, xb, yb, T, gen)
    elif arm == "replay":
        gen = torch.Generator().manual_seed(seed + 202)
        train(model, params, xa, ya, steps, gen)
        a0 = acc(model, *data["A"]["test"])
        train(model, params, xb, yb, steps, gen)
        sel = torch.randint(0, xa.shape[0], (200,), generator=gen)
        train(model, params, xa[sel], ya[sel], T, gen)
    else:
        gen = torch.Generator().manual_seed(seed + 303)
        train(model, params, xa, ya, steps, gen)
        a0 = acc(model, *data["A"]["test"])
        # phase B: the head is frozen, a transient expert carries the new task
        transient = Expert()
        model.experts.append(transient)
        for p in model.head.parameters():
            p.requires_grad_(False)
        train(model, [model.trunk.weight, model.trunk.bias, transient.A, transient.B],
              xb, yb, steps, gen)
        # the teacher is the model as it stands at the end of the wake phase
        teacher = Net(n_experts=len(model.experts))
        teacher.load_state_dict(model.state_dict())
        for p in teacher.parameters():
            p.requires_grad_(False)
        # prune the transient expert; the fresh one starts at zero
        with torch.no_grad():
            transient.A.zero_()
            transient.B.zero_()
        prompts = torch.cat([xa, xb])
        consolidate(model, teacher, prompts, T, gen)
        for p in model.head.parameters():
            p.requires_grad_(True)
        if arm == "sleep_dream":
            dream(model, prompts, dream_steps, gen)
    a1 = acc(model, *data["A"]["test"])
    b1 = acc(model, *data["B"]["test"])
    return dict(arm=arm, seed=seed, a0=round(a0, 4), a1=round(a1, 4), b1=round(b1, 4),
                forgetting=round(a0 - a1, 4), avg_acc=round((a1 + b1) / 2, 4),
                seconds=round(time.perf_counter() - t0, 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--sleep-steps", type=int, default=200)
    ap.add_argument("--dream-steps", type=int, default=200)
    ap.add_argument("--seed0", type=int, default=3)
    ap.add_argument("--out", default="results.json")
    args = ap.parse_args()
    st = box_state()
    print("box state:", file=sys.stderr)
    print(format_box_state(st), file=sys.stderr)
    arms = ["seq", "seq_extra", "replay", "sleep", "sleep_dream"]
    rows = []
    for arm in arms:
        for s in range(args.seed0, args.seed0 + args.seeds):
            r = run(arm, s, args.steps, args.sleep_steps, args.dream_steps)
            rows.append(r)
            print(f"{arm:12s} seed {s:2d}  a0 {r['a0']:.3f}  a1 {r['a1']:.3f}  b1 {r['b1']:.3f}"
                  f"  forget {r['forgetting']:+.3f}  avg {r['avg_acc']:.3f}  {r['seconds']:.1f}s",
                  file=sys.stderr)
    summary = {}
    for arm in arms:
        sel = [r for r in rows if r["arm"] == arm]
        summary[arm] = {
            k: {"mean": round(sum(r[k] for r in sel) / len(sel), 4),
                "min": round(min(r[k] for r in sel), 4),
                "max": round(max(r[k] for r in sel), 4),
                "n": len(sel)}
            for k in ("a0", "a1", "b1", "forgetting", "avg_acc", "seconds")
        }
    print()
    print("| arm | a0 | a1 (A kept) | b1 (B learned) | forgetting | avg acc |")
    print("|---|---|---|---|---|---|")
    for arm in arms:
        s = summary[arm]
        print(f"| `{arm}` | {s['a0']['mean']:.3f} | {s['a1']['mean']:.3f}"
              f" [{s['a1']['min']:.3f}, {s['a1']['max']:.3f}] |"
              f" {s['b1']['mean']:.3f} [{s['b1']['min']:.3f}, {s['b1']['max']:.3f}] |"
              f" {s['forgetting']['mean']:.3f}"
              f" [{s['forgetting']['min']:.3f}, {s['forgetting']['max']:.3f}] |"
              f" {s['avg_acc']['mean']:.3f}"
              f" [{s['avg_acc']['min']:.3f}, {s['avg_acc']['max']:.3f}] |")
    Path(args.out).write_text(json.dumps(
        {"config": vars(args), "box_state": st, "rows": rows, "summary": summary}, indent=2))
    print(f"\nwrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
