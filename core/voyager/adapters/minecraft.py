"""The Minecraft adapter — the first world the loop plays in.

The world is a **private** Paper server: the server directory is copied
out of the live agent-world tree into ``mc-sandbox/``, it is given a new
world, it is bound to ``127.0.0.1`` on port **25600**, and it runs in
offline mode. The live server on 25565 and its world are never touched —
that is the rule in the brief and the reason the copy exists.

What the adapter adds to the core is three things and nothing else:

* **the facts** — what a player would say about the world right now;
* **the vocabulary** — the closed set of primitives a skill may call;
* **the ground truth** — the world's own answer to "is this milestone
  met", read off the inventory.

The bot is mineflayer, driven by ``minecraft_bridge.js``, which is a
separate process speaking line-delimited JSON. The split is deliberate:
the sandbox that runs model-written code belongs on the node side, next
to the bot, where the ``vm`` module and the game's own API are.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..models import Milestone
from ..ports import CheckResult, EnvironmentPort, ExecResult, ProgressSnapshot
from ..vocab import BODY_SCHEMA, BODY_WORD, SkillVocabulary
from .minecraft_items import BLOCK_IDS, ITEM_IDS

__all__ = [
    "MinecraftAdapter",
    "MC_MILESTONES",
    "mc_vocabulary",
    "BRIDGE_PATH",
]

#: Where the node bridge lives.
BRIDGE_PATH = Path(__file__).with_name("minecraft_bridge.js")

#: The vanilla item ids, as a list, for the schemas.
_ITEMS = list(ITEM_IDS)
_BLOCKS = list(BLOCK_IDS)

_ITEM_HINT = (
    "a vanilla item id, e.g. oak_log, oak_planks, stick, crafting_table, "
    "cobblestone, stone_pickaxe, coal, furnace, iron_ore, raw_iron, iron_ingot"
)
_BLOCK_HINT = (
    "a vanilla block id, e.g. oak_log, cobblestone, stone, coal_ore, iron_ore, "
    "crafting_table, furnace, deepslate_iron_ore"
)

#: The tech tree, as the curriculum's milestones.
#:
#: The order is the world's own: wood, then planks, then a table and a
#: wooden pickaxe, then stone, then iron. The dependencies are the
#: branches in it — a table and a wooden pickaxe are both open once the
#: planks are, and a furnace and an iron pickaxe are both open later —
#: so the curriculum has more than one thing to try at the hard stages.
MC_MILESTONES: tuple[Milestone, ...] = (
    Milestone(
        key="wood",
        title="get wood",
        description="Break a tree and pick up the logs.",
        items=(
            "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log",
            "dark_oak_log",
        ),
    ),
    Milestone(
        key="planks",
        title="turn the wood into planks",
        description="Craft planks from the logs.",
        needs=("wood",),
        items=(
            "oak_planks", "birch_planks", "spruce_planks", "jungle_planks",
            "acacia_planks", "dark_oak_planks",
        ),
    ),
    Milestone(
        key="crafting_table",
        title="make a crafting table",
        description="Craft a crafting table from four planks.",
        needs=("planks",),
        items=("crafting_table",),
    ),
    Milestone(
        key="wooden_pickaxe",
        title="make a wooden pickaxe",
        description="Craft a wooden pickaxe; it is needed for stone.",
        needs=("planks",),
        items=("wooden_pickaxe",),
    ),
    Milestone(
        key="stone",
        title="get stone",
        description="Mine cobblestone with the wooden pickaxe.",
        needs=("wooden_pickaxe",),
        items=("cobblestone",),
    ),
    Milestone(
        key="stone_pickaxe",
        title="make a stone pickaxe",
        description="Craft a stone pickaxe; it is needed for iron.",
        needs=("stone",),
        items=("stone_pickaxe",),
    ),
    Milestone(
        key="furnace",
        title="make a furnace",
        description="Craft a furnace from cobblestone.",
        needs=("stone",),
        items=("furnace",),
    ),
    Milestone(
        key="iron",
        title="get iron",
        description="Mine iron ore and bring the raw iron up.",
        needs=("stone_pickaxe",),
        items=("raw_iron", "iron_ingot"),
    ),
    Milestone(
        key="iron_pickaxe",
        title="make an iron pickaxe",
        description="Craft an iron pickaxe from three iron ingots and two sticks.",
        needs=("iron",),
        items=("iron_pickaxe",),
    ),
)


def _string_enum(values: Sequence[str], hint: str) -> dict[str, Any]:
    return {"type": "string", "enum": list(values), "hint": hint}


def mc_vocabulary() -> SkillVocabulary:
    """The closed primitive set of the Minecraft world.

    The schemas are the *whole* vanilla id list, so the door refuses an
    item that does not exist; the ``hint`` on each one is what the
    coder prompt shows, because a prompt that carries sixteen hundred
    item ids is a prompt nobody reads.
    """
    words: dict[str, Mapping[str, Any]] = {
        "mc.move_to": {
            "x": {"type": "number", "minimum": -100000, "maximum": 100000},
            "y": {"type": "number", "minimum": -1000, "maximum": 1000},
            "z": {"type": "number", "minimum": -100000, "maximum": 100000},
            "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 600000},
        },
        "mc.move_to_block": {
            "block": _string_enum(_BLOCKS, _BLOCK_HINT),
            "max_distance": {"type": "integer", "minimum": 1, "maximum": 128},
            "timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 600000},
        },
        "mc.mine_block": {
            "block": _string_enum(_BLOCKS, _BLOCK_HINT),
            "max_distance": {"type": "integer", "minimum": 1, "maximum": 64},
            "count": {"type": "integer", "minimum": 1, "maximum": 64},
        },
        "mc.collect": {
            "item": _string_enum(_ITEMS, _ITEM_HINT),
            "count": {"type": "integer", "minimum": 1, "maximum": 64},
            "max_distance": {"type": "integer", "minimum": 1, "maximum": 64},
        },
        "mc.craft": {
            "item": _string_enum(_ITEMS, _ITEM_HINT),
            "count": {"type": "integer", "minimum": 1, "maximum": 64},
        },
        "mc.place_block": {
            "block": _string_enum(_BLOCKS, _BLOCK_HINT),
            "x": {"type": "integer", "minimum": -100000, "maximum": 100000},
            "y": {"type": "integer", "minimum": -1000, "maximum": 1000},
            "z": {"type": "integer", "minimum": -100000, "maximum": 100000},
        },
        "mc.place_adjacent": {
            "block": _string_enum(_BLOCKS, _BLOCK_HINT),
        },
        "mc.equip": {
            "item": _string_enum(_ITEMS, _ITEM_HINT),
        },
        "mc.equip_tool": {
            "kind": {
                "type": "string",
                "enum": ["pickaxe", "axe", "shovel", "sword"],
                "hint": "the kind of tool to hold",
            },
        },
        "mc.look_at": {
            "x": {"type": "number", "minimum": -100000, "maximum": 100000},
            "y": {"type": "number", "minimum": -1000, "maximum": 1000},
            "z": {"type": "number", "minimum": -100000, "maximum": 100000},
        },
        "mc.sleep": {
            "ms": {"type": "integer", "minimum": 0, "maximum": 600000},
        },
        "mc.scan": {
            "radius": {"type": "integer", "minimum": 1, "maximum": 160},
        },
        "mc.smelt": {
            "item": _string_enum(_ITEMS, _ITEM_HINT),
            "count": {"type": "integer", "minimum": 1, "maximum": 64},
            "fuel": {"type": "string", "enum": ["coal", "charcoal", "oak_planks", "birch_planks"],
                     "hint": "what to burn"},
        },
        "mc.scan_ore": {
            "radius": {"type": "integer", "minimum": 1, "maximum": 32},
        },
        "mc.dig_down": {
            "steps": {"type": "integer", "minimum": 1, "maximum": 48},
        },
        "mc.count": {
            "item": _string_enum(_ITEMS, _ITEM_HINT),
        },
        "mc.has": {
            "item": _string_enum(_ITEMS, _ITEM_HINT),
        },
        BODY_WORD: BODY_SCHEMA,
    }
    return SkillVocabulary(words)


class MinecraftAdapter:
    """The Minecraft world, as an environment.

    The adapter owns the node process and the JSON line protocol; the
    core never sees either.
    """

    name = "minecraft"
    language = "javascript"

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 25600,
        username: str = "voyager",
        node: str | None = None,
        minecraft_dir: str | None = None,
        version: str = "26.1.2",
        timeout_s: float = 180.0,
        stderr_path: str | None = None,
        log=None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.version = version
        self.timeout_s = timeout_s
        self._log = log or (lambda message: None)
        self._node = node or os.environ.get(
            "VOYAGER_NODE", "/home/caseydigennaro/lm-wt/agent-world/runtime/node/bin/node"
        )
        self._minecraft_dir = minecraft_dir or os.environ.get(
            "VOYAGER_MINECRAFT_DIR", "/home/caseydigennaro/lm-wt/agent-world/bots"
        )
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._lock = threading.Lock()
        self.stderr_path = str(
            stderr_path
            or os.environ.get(
                "VOYAGER_BRIDGE_STDERR",
                "/tmp/voyager-bridge-stderr.log",
            )
        )
        self._items: dict[str, int] = {}
        self._milestones = {m.key: m for m in MC_MILESTONES}
        self._registry = mc_vocabulary()

    # -- the world -------------------------------------------------------------

    def open(self) -> None:
        """Start the bridge and connect the bot."""
        if self._process is not None:
            return
        env = dict(os.environ)
        env["VOYAGER_MC_HOST"] = self.host
        env["VOYAGER_MC_PORT"] = str(self.port)
        env["VOYAGER_MC_USER"] = self.username
        env["VOYAGER_MC_VERSION"] = self.version
        env["VOYAGER_MINECRAFT_DIR"] = self._minecraft_dir
        self._process = subprocess.Popen(
            [self._node, str(BRIDGE_PATH)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self._drain_stderr()
        self._call("connect", timeout_s=120.0)
        self._log(f"the bot is connected to {self.host}:{self.port}")

    def close(self) -> None:
        """Stop the bridge, politely."""
        if self._process is None:
            return
        try:
            self._call("quit", timeout_s=10.0)
        except Exception:
            pass
        try:
            self._process.terminate()
            self._process.wait(timeout=10)
        except Exception:
            try:
                self._process.kill()
            except Exception:
                pass
        self._process = None

    def _drain_stderr(self) -> None:
        """Read the bridge's stderr in a thread, so it never blocks.

        The bridge's stderr is also written to a file beside the run:
        it is the only place the bridge's own account of itself appears,
        and a crash there explains a death that the protocol alone does
        not.
        """

        def reader() -> None:
            process = self._process
            if process is None or process.stderr is None:
                return
            try:
                handle = open(self.stderr_path, "a")
            except Exception:
                handle = None
            try:
                for line in process.stderr:
                    self._log("bridge: " + line.rstrip())
                    if handle is not None:
                        handle.write(line)
                        handle.flush()
            finally:
                if handle is not None:
                    handle.close()

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()

    def _call(self, cmd: str, *, timeout_s: float | None = None, **payload: Any) -> Any:
        """One request, one response, over the line protocol."""
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("the bridge is not running")
        answer: dict[str, Any] | None = None
        skipped: list[str] = []
        with self._lock:
            self._next_id += 1
            request = {"id": self._next_id, "cmd": cmd}
            request.update(payload)
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            # A line that is not a JSON object means something wrote to
            # the bridge's stdout that was not a response. The line is
            # the only evidence of what got in the way, so it is kept
            # and shown; but a stray line is not the end of the run, so
            # the lines are read until the answer arrives.
            for _ in range(64):
                line = process.stdout.readline()
                if not line:
                    break
                try:
                    answer = json.loads(line)
                    break
                except ValueError:
                    skipped.append(line.rstrip())
        if answer is None:
            if skipped:
                raise RuntimeError(
                    "the bridge sent no answer; the lines that were not JSON were "
                    + repr(skipped[:5])
                )
            raise RuntimeError("the bridge closed the pipe")
        if skipped:
            self._log(
                f"bridge: {len(skipped)} lines that were not JSON were skipped: "
                + repr(skipped[:3])
            )
        if not answer.get("ok"):
            raise RuntimeError(str(answer.get("error", "the bridge refused the request")))
        return answer.get("result")

    # -- the environment -------------------------------------------------------

    def observe(self) -> dict[str, Any]:
        """The facts, in the player's terms."""
        raw = self._call("observe", timeout_s=self.timeout_s)
        inventory = dict(raw.get("inventory") or {})
        self._items = inventory
        nearby: dict[str, Any] = {}
        ores: dict[str, Any] = {}
        # A scan is a read, and the facts are worth the two calls: a
        # player knows what is in reach.
        # The facts are what the planner reasons over, so they are the
        # world as a player would describe it: what is in reach and what
        # is in the world around. The scan reaches the loaded area of
        # the server, which is where the tree is when the tree is 86
        # blocks away; a scan of sixteen blocks says "empty" and hides
        # the only thing worth doing.
        try:
            nearby = (self._call("run", timeout_s=45.0, code="return await mc.scan(96)", timeout_ms=30000) or {}).get("nearby", {})
        except Exception:
            nearby = {}
        try:
            ores = (self._call("run", timeout_s=45.0, code="return await mc.scan_ore(32)", timeout_ms=30000) or {}).get("ores", {})
        except Exception:
            ores = {}
        return {
            "world": "minecraft",
            "position": raw.get("position"),
            "health": raw.get("health"),
            "food": raw.get("food"),
            "held": raw.get("held"),
            "time_of_day": raw.get("time_of_day"),
            "inventory": inventory,
            "nearby": nearby,
            "ores": ores,
            "milestones": {
                key: self._truth_of(key) for key in self._milestones
            },
        }

    def run_code(self, code: str, *, timeout_s: float) -> ExecResult:
        """Run a skill in the bridge's sandbox."""
        try:
            result = self._call(
                "run", timeout_s=timeout_s + 30.0, code=code, timeout_ms=int(timeout_s * 1000)
            )
        except Exception as exc:
            return ExecResult(ok=False, error=str(exc)[:600], log=(), seconds=0.0)
        log = tuple(str(line) for line in (result.get("log") or []))
        return ExecResult(
            ok=True,
            error="",
            log=log,
            seconds=float(result.get("seconds") or 0.0),
        )

    def evaluate(self, code: str, *, timeout_s: float) -> CheckResult:
        """Run a self-verification snippet."""
        try:
            result = self._call(
                "evaluate",
                timeout_s=timeout_s + 30.0,
                code=code,
                timeout_ms=int(timeout_s * 1000),
            )
        except Exception as exc:
            return CheckResult(passed=False, detail=str(exc)[:400], seconds=0.0)
        return CheckResult(
            passed=bool(result.get("passed")),
            detail=str(result.get("value") or ""),
            seconds=float(result.get("seconds") or 0.0),
        )

    def goal_truth(self, key: str) -> bool:
        """The world's own answer: is this milestone met?

        It is read off the inventory, not off the model's opinion.
        """
        return self._truth_of(key)

    def progress(self) -> ProgressSnapshot:
        """The counts the report quotes."""
        try:
            result = self._call("progress", timeout_s=30.0)
            self._items = dict(result.get("inventory") or {})
        except Exception:
            pass
        return ProgressSnapshot(
            unique_items=len([name for name, count in self._items.items() if count > 0]),
            items={k: v for k, v in sorted(self._items.items()) if v > 0},
            milestones={key: self._truth_of(key) for key in self._milestones},
        )

    def primitives(self) -> tuple[str, ...]:
        """The closed set of primitives this world exposes."""
        return self._registry.words()

    def primitive_schemas(self) -> Mapping[str, Any]:
        """The primitives and their schemas, for the coder prompt."""
        return self._registry.schema_map()

    def milestones(self) -> tuple[Milestone, ...]:
        return MC_MILESTONES

    # -- internals -------------------------------------------------------------

    def _truth_of(self, key: str) -> bool:
        milestone = self._milestones.get(key)
        if milestone is None:
            return False
        return any(self._items.get(name, 0) > 0 for name in milestone.items)
