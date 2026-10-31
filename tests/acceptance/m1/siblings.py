"""Materialize the sibling seats' code from their branches — no merging.

The brief's rule: the parts of the core that are not on `main` yet live on
sibling branches (`core-api` in progress; `core-recipe`, `vocab`, `why-kernel`,
`night-runner`, `cold-start`, `usd-backbone` done or near). We read them with
`git show <branch>:<path>` — never `git merge` — into a scratch directory
under `tests/acceptance/m1/.siblings/`, and import them under names that
cannot collide:

===============  =======================  ====================================
branch           imported as              how
===============  =======================  ====================================
`core-api`       `sib_api`                alias-loaded package (its
                                          `core/__init__.py` is a regular
                                          package that would otherwise shadow
                                          the namespace seats below)
`core-recipe`    `builder_recipe`         its own top-level name (unique)
`vocab`          `core.vocab`             PEP 420 namespace `core`
`cold-start`     `core.coldstart`         PEP 420 namespace `core`
`night-runner`   `core.night`             PEP 420 namespace `core` — the
                                          branch's own `core/__init__.py` is
                                          deliberately NOT materialized
`why-kernel`     `core.why`,              PEP 420 namespace `core`; its stub
                 `core.justification`     `core.api`/`core.recipe` are kept
                                          (justification imports them), its
                                          `core.vocab` stub is NOT (the real
                                          vocab answers that import)
===============  =======================  ====================================

`usd-backbone` is not materialized: it needs the `usd-core`/`build123d`
wheels, and the M1 slice's render rungs run against the stub generator by
design (plan §2 M1 risks: "if the bpy wheel is late, M1 runs its render
rungs against a stub generator"). The README says where it plugs in.

Everything here is scratch: `.siblings/` is gitignored, rebuilt when a
branch's head moves, and nothing on any branch is modified.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CACHE = _HERE / ".siblings"

#: branch -> (paths to materialize, whether its `core/__init__.py` must be
#: dropped so `core` stays a PEP 420 namespace, note)
MATERIALIZE: dict[str, tuple[tuple[str, ...], bool, str]] = {
    "core-api": (("core", "pyproject.toml"), False,
                 "the HTTP spine (§4.2) — alias-loaded, keeps its __init__"),
    "core-recipe": (("core/src",), False,
                    "recipe store, node registry (§1.1–§1.4)"),
    "vocab": (("core/vocab",), False, "words, the door, sealed bets, Prop-maker (§1.5–§1.7)"),
    "cold-start": (("core/coldstart",), False,
                   "the cold open, ask-mode, the melt (§3.5)"),
    "night-runner": (("core/night",), True,
                     "queue, rails, heartbeat, status, report (§3.2–§3.4)"),
    "why-kernel": (("core/why", "core/justification", "core/api", "core/recipe"),
                   True, "why-chains (§1.6 provenance's sibling)"),
}

#: bump to invalidate materialized copies after a change to the layout above
_LAYOUT_VERSION = 2

#: how the namespace `core` is assembled: subpackage -> (branch, subpath)
_NAMESPACE: dict[str, tuple[str, str]] = {
    "vocab": ("vocab", "core/vocab"),
    "coldstart": ("cold-start", "core/coldstart"),
    "night": ("night-runner", "core/night"),
    "why": ("why-kernel", "core/why"),
    "justification": ("why-kernel", "core/justification"),
    # why-kernel's own stubs for the seats it reads (core.justification
    # imports core.api / core.recipe); its core.vocab stub is skipped —
    # the real vocabulary answers that import in this tree.
    "api": ("why-kernel", "core/api"),
    "recipe": ("why-kernel", "core/recipe"),
}


def _git(*args: str) -> str:
    root = _HERE.parents[2]
    out = subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )
    return out.stdout


def _branch_head(branch: str) -> str:
    return _git("rev-parse", branch).strip()


@dataclass
class Seats:
    """The loaded sibling modules, by seat name."""

    api: object          # sib_api            (branch core-api)
    recipe: object       # builder_recipe     (branch core-recipe)
    vocab: object        # core.vocab         (branch vocab)
    coldstart: object    # core.coldstart     (branch cold-start)
    night: object        # core.night         (branch night-runner)
    why: object          # core.why           (branch why-kernel)
    justification: object  # core.justification (branch why-kernel)

    @property
    def heads(self) -> dict[str, str]:
        return dict(self._heads)  # type: ignore[attr-defined]


def materialize(branch: str, paths: tuple[str, ...], *, drop_core_init: bool = False) -> Path:
    """Write the branch's files under `.siblings/<branch>/` via `git show`.

    Idempotent per branch head and layout version: a stamp records both, and
    a change to either triggers a clean rebuild.
    """
    dest = CACHE / branch
    head = _branch_head(branch)
    stamp_content = f"{head}\nlayout:{_LAYOUT_VERSION}"
    stamp = dest / ".stamp"
    if stamp.exists() and stamp.read_text() == stamp_content:
        return dest
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    listing = []
    for path in paths:
        listing += _git("ls-tree", "-r", "--name-only", branch, "--", path).split()
    for path in listing:
        if drop_core_init and path.endswith("core/__init__.py"):
            # keep `core` a PEP 420 namespace across the seats
            continue
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_git("show", f"{branch}:{path}"))
    stamp.write_text(stamp_content)
    return dest


def _alias_import(name: str, pkg_dir: Path):
    """Import a package directory under an alias top-level name."""
    init = pkg_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(pkg_dir)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load() -> Seats:
    """Materialize every seat and import it. Returns the seat modules."""
    import json

    for branch, (paths, drop_core_init, _note) in MATERIALIZE.items():
        materialize(branch, paths, drop_core_init=drop_core_init)
    api_dir = CACHE / "core-api" / "core"
    recipe_src = CACHE / "core-recipe" / "core" / "src"

    ns = CACHE / "ns"
    heads = {b: _branch_head(b) for b in MATERIALIZE}
    stamp = ns / ".stamp"
    ns_stamp = f"{__import__('json').dumps(heads, sort_keys=True)}\nlayout:{_LAYOUT_VERSION}"
    if not stamp.exists() or stamp.read_text() != ns_stamp:
        if ns.exists():
            shutil.rmtree(ns)
        core_dir = ns / "core"
        core_dir.mkdir(parents=True)
        for sub, (branch, subpath) in _NAMESPACE.items():
            shutil.copytree(CACHE / branch / subpath, core_dir / sub)
        stamp.write_text(ns_stamp)

    # `core` must stay a PEP 420 namespace: core-api's own `core/` is a
    # regular package, so its directory must NOT be on sys.path (a regular
    # package anywhere on the path beats namespace portions). It is loaded
    # under its alias directly, through `sib_api.__path__`.
    for extra in (str(recipe_src), str(ns)):
        if extra not in sys.path:
            sys.path.insert(0, extra)

    api = _alias_import("sib_api", api_dir)
    import builder_recipe  # noqa: F401  (top-level name, no collision)
    import core.vocab as vocab
    import core.coldstart as coldstart
    import core.night as night
    import core.why as why
    import core.justification as justification

    seats = Seats(
        api=api, recipe=builder_recipe, vocab=vocab, coldstart=coldstart,
        night=night, why=why, justification=justification,
    )
    seats._heads = heads  # type: ignore[attr-defined]
    return seats
