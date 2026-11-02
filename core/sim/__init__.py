"""`core/sim` -- the batched simulator: one interface, many rule systems.

A **batch** is a set of independent worlds of one rule system, stepped
together on the GPU. The interface is the one the design names
(`docs/design/batched-sim.md` §1): a fixed-size POD state per world, a legal
action mask written by the rules engine, and observation planes from the
acting player's point of view.

```python
from core.sim import make_batch

batch = make_batch("beacons", num_envs=1024, rows=1, device="cuda", seed=7)
mask = batch.legal_action_mask()     # (num_envs, A) bool
obs = batch.obs()                     # (num_envs, C, H, W) float32
batch.apply_actions(actions)          # actions: int32 (num_envs,)
```

Every array the binding returns is a **fresh copy**: the backend reuses its
buffers, so a tensor kept across a step would otherwise change under the
caller's feet.

The arrays are numpy. A caller that has torch gets a tensor for free with
`core.sim.to_torch`, and `torch.from_numpy` keeps the shape, so nothing
upstream has to change shape.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from . import _pysim

__all__ = ["make_batch", "systems", "to_torch", "seed_table"]

__version__ = "0.1.0"


def systems() -> list[dict[str, Any]]:
    """Every registered rule system, with its shape.

    Each entry carries the action count, the observation shape, and the byte
    sizes the trajectory proof compares.
    """
    return list(_pysim.systems())


def seed_table(num_envs: int, seed: int = 0) -> list[int]:
    """A seed table with one stream per world.

    The worlds are different, and the batch is reproducible: the same seed
    gives the same worlds, every time, on every machine.
    """
    return [seed + i for i in range(num_envs)]


def make_batch(
    system: str,
    num_envs: int = 1024,
    rows: int = 1,
    device: str = "cuda",
    seed: int = 0,
    params: Mapping[str, float] | None = None,
):
    """Make a batch of `num_envs` worlds of `system`.

    `rows` is the depth of the rollout buffer: the states of the last `rows`
    steps are kept, one row per step, which is what the trajectory proof
    compares. `device` is `"cuda"` or `"cpu"`. `params` are the system's own
    parameters, by name; the ones left out keep their defaults.
    """
    return _pysim.make_batch(
        system, int(num_envs), int(rows), str(device), int(seed), dict(params or {})
    )


def to_torch(array: Any):
    """A numpy array as a torch tensor, sharing its memory.

    torch is not installed on the Thor by default, so this is the only place
    the module reaches for it.
    """
    import torch  # imported here: the core does not depend on torch

    return torch.from_numpy(array)
