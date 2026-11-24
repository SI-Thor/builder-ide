"""The reflex service, the mediator and the reports.

    python -m agent_world_reflex serve      # the decision seam (loopback)
    python -m agent_world_reflex observe    # is the sign holding?
    python -m agent_world_reflex mediate    # step in, if the sign has faded
    python -m agent_world_reflex report     # the numbers
    python -m agent_world_reflex seed       # install the starting skills
    python -m agent_world_reflex skills     # what is in the library
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from .chooser import Chooser
from .decision import DecisionModel
from .library import SkillLibrary, build_skill
from .ledger import WorldLedger
from .mediator import Mediator
from .models import SkillAuthor
from .service import ReflexService, serve

RUNTIME = Path(os.environ.get("AW_RUNTIME", str(Path.home() / "lm-wt" / "agent-world" / "runtime")))
SKILLS_DIR = RUNTIME / "skills"
LEDGER_PATH = RUNTIME / "world-ledger.sqlite3"
SEED_DIR = Path(os.environ.get("AW_SEED_DIR", str(Path(__file__).resolve().parent.parent / "skills" / "seed")))


def _library(on_retire=None) -> SkillLibrary:
    return SkillLibrary(SKILLS_DIR, on_retire=on_retire)


def _ledger() -> WorldLedger:
    return WorldLedger(LEDGER_PATH)


def cmd_serve() -> int:
    library = _library()
    ledger = _ledger()
    chooser = Chooser()
    # The chooser is a fold over the log, so it starts where the log ends.
    records = ledger.plays()
    if records:
        chooser.fit(records)
    model = DecisionModel(
        port=int(os.environ.get("AW_D1_PORT", "8094")),
        ledger=ledger,
    )
    service = ReflexService(library=library, chooser=chooser, model=model, ledger=ledger)
    host = os.environ.get("AW_REFLEX_HOST", "127.0.0.1")
    port = int(os.environ.get("AW_REFLEX_PORT", "8110"))
    server = serve(service, host=host, port=port)
    print(f"the reflex is listening on {host}:{port}", flush=True)
    print(f"  skills: {len(library.active())} active of {len(library.all())}", flush=True)
    print(f"  plays folded from the log: {len(records)}", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.shutdown()
    return 0


def cmd_observe() -> int:
    mediator = Mediator(library=_library(), ledger=_ledger())
    sign = mediator.observe()
    print(json.dumps(sign, indent=2))
    return 0


def cmd_mediate() -> int:
    mediator = Mediator(
        library=_library(),
        ledger=_ledger(),
        max_calls=int(os.environ.get("AW_MEDIATOR_CALLS", "4")),
    )
    result = mediator.step_in()
    print(json.dumps(result, indent=2, default=str))
    return 0


def cmd_report() -> int:
    library = _library()
    ledger = _ledger()
    chooser = Chooser()
    records = ledger.plays()
    chooser.fit(records)
    mediator = Mediator(library=library, ledger=ledger)
    report = {
        "skills": {
            "total": len(library.all()),
            "active": len(library.active()),
            "retired": len(library.all()) - len(library.active()),
            "families": list(library.families()),
        },
        "plays": {
            "count": len(records),
            "wins": len([r for r in records if r.outcome.result == "win"]),
            "losses": len([r for r in records if r.outcome.result == "lose"]),
            "partial": len([r for r in records if r.outcome.result == "partial"]),
        },
        "sign": mediator.observe(),
        "chooser": chooser.stats(),
    }
    print(json.dumps(report, indent=2, default=str))
    return 0


def cmd_retire() -> int:
    """Retire a skill. Its body and its plays stay; it is never deleted."""
    skill_id = sys.argv[2] if len(sys.argv) > 2 else ""
    reason = sys.argv[3] if len(sys.argv) > 3 else "retired by hand"
    if not skill_id:
        print("usage: python -m agent_world_reflex retire <skill_id> [reason]")
        return 1
    ledger = _ledger()
    library = _library()
    retired = library.retire(skill_id, reason=reason)
    ledger.retired(retired, reason=reason)
    print(f"retired {retired.id} ({retired.family}): {reason}")
    return 0


def cmd_skills() -> int:
    for skill in _library().all():
        print(
            f"{skill.id}  v{skill.version}  {skill.status:8s}  {skill.role:9s} "
            f"{skill.family:22s} {skill.title}"
        )
    return 0


def cmd_seed() -> int:
    ledger = _ledger()
    library = _library(
        on_retire=lambda skill, reason: ledger.retired(skill, reason=reason)
    )
    count = 0
    for path in sorted(SEED_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        author = SkillAuthor(**raw["author"])
        skill = build_skill(
            family=raw["family"],
            role=raw["role"],
            title=raw["title"],
            body=raw["body"],
            author=author,
            kind=raw.get("kind", "behaviour"),
            preconditions=raw.get("preconditions", []),
            predict=raw.get("predict", {"kind": "none"}),
            provenance=raw.get("provenance", {}),
        )
        admitted = library.add(skill)
        if admitted.version == 1:
            ledger.authored(admitted)
            count += 1
    # The library reconciles itself: the latest version of a family is
    # the live one, and the earlier attempts are retired with a reason.
    retired = library.sweep()
    print(f"{count} skills admitted into the library at {SKILLS_DIR}")
    if retired:
        print(f"{len(retired)} superseded version(s) retired")
    return 0


COMMANDS = {
    "serve": cmd_serve,
    "observe": cmd_observe,
    "mediate": cmd_mediate,
    "report": cmd_report,
    "skills": cmd_skills,
    "seed": cmd_seed,
    "retire": cmd_retire,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "report"
    handler = COMMANDS.get(command)
    if handler is None:
        print(__doc__)
        return 1
    return handler()


if __name__ == "__main__":
    raise SystemExit(main())
