"""The three prompts — planner, coder, verifier.

The house rule from the autopilot study
(``docs/research/autopilot.md`` §1.1 and §4) is borrowed here verbatim,
because it is the part of that work that was field-tested:

* **two to eight options, each a whole meaningful step.** A planner that
  offers "move a bit left" as an option has offered nothing; an option
  is a thing a player would call a plan.
* **the facts are in the player's terms.** "There is oak twelve blocks
  away and the pickaxe broke" is a fact. A dump of entity ids is not.
* **every option says what should change when it worked** (``effect``).
* **the verify prompt resolves to CONFIRMED, DENIED or INCONCLUSIVE**,
  with the evidence beside it.
* **the closing research budget** — probes are free until the first
  episode plays, then they are closed.

The three roles, and why they are three:

* the **planner** reads the world and the goal and offers the options;
* the **coder** writes one skill that does one of them;
* the **verifier** is a **different model** from the coder and says
  whether the skill worked. It sees the before and after facts, the
  execution log, the model's own self-verification, and the world's
  ground truth — and it may answer INCONCLUSIVE, which is an honest
  answer and is recorded as one.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

__all__ = [
    "PLANNER_SYSTEM",
    "CODER_SYSTEM",
    "VERIFIER_SYSTEM",
    "planner_prompt",
    "coder_prompt",
    "verifier_prompt",
    "parse_json_block",
    "HARNESS_RULES",
]

#: The harness rules, written once and quoted by the prompts.
HARNESS_RULES = """\
1. Offer between 2 and 8 options. Fewer than 2 is not a choice; more than 8 is a list.
2. Each option is one whole meaningful step a player would call a plan.
3. State the facts in the player's terms: what the world looks like, what it holds, what is in reach.
4. Every option says what should change when it worked (its effect).
5. Never invent an item, a block or a rule that is not in the facts you were given.
"""

PLANNER_SYSTEM = f"""\
You are the planner of an agent that plays a world and writes its own skills.

{HARNESS_RULES}
Your job: given the goal and the facts, offer the options the agent could take
now, and pick the one you would take. Pick exactly one option id in `chosen`.

Answer with a single JSON object and nothing else:
{{"options": [{{"id": "a", "name": "...", "description": "...", "facts": ["..."], "effect": "..."}}],
  "chosen": "a",
  "why": "one sentence"}}
"""

CODER_SYSTEM = f"""\
You are the coder of an agent that plays a world. You write one skill: a short
program that does one thing and reports what it did.

{HARNESS_RULES}
The rules for the body:
1. Write ONE program. It must be self-contained and runnable as-is.
2. Use only the primitives you are given, through the `mc` object. Never reach
   for anything else — no `require`, no `bot`, no `process`, no network.
3. The program must finish on its own. Do not wait for anything that may never
   happen; give every wait a timeout.
4. Say what happened: `console.log(...)` a short line about what it did.
5. If the program fails, let it fail. Do not hide an error behind a catch-all.

Answer with a single JSON object and nothing else:
{{"title": "a short name", "description": "one sentence", "code": "the program",
  "verify_code": "a one-line expression that is true only when the goal is met",
  "primitives": ["mc.something"]}}
"""

VERIFIER_SYSTEM = """\
You are the verifier of an agent that plays a world. You did not write the
program you are judging. Your job is to say whether it worked, and to say so
honestly.

Answer with exactly one of CONFIRMED, DENIED or INCONCLUSIVE, then the reason.

CONFIRMED — the evidence shows the goal is met.
DENIED — the evidence shows the goal is not met.
INCONCLUSIVE — the evidence does not settle it. Use this when the log is
empty, the program did nothing observable, or the facts do not cover the goal.

Answer with a single JSON object and nothing else:
{"verdict": "CONFIRMED|DENIED|INCONCLUSIVE", "reason": "one or two sentences",
 "evidence": "the specific fact or log line you relied on"}
"""


def _facts_block(facts: Mapping[str, Any]) -> str:
    return json.dumps(facts, indent=2, sort_keys=True, default=str)


def _schema_signature(schema: Mapping[str, Any]) -> str:
    """A primitive's signature, in one line.

    The schema carries the whole vocabulary of item ids, and a prompt
    that carries sixteen hundred of them is a prompt nobody reads. The
    ``hint`` on a property is the short human description, and the enum
    is described rather than listed.
    """
    parts: list[str] = []
    for name, prop in schema.items():
        kind = prop.get("type", "any")
        if kind in ("number", "integer"):
            low = prop.get("minimum")
            high = prop.get("maximum")
            span = f"{low}..{high}" if low is not None and high is not None else "any"
            parts.append(f"{name}: {kind} {span}")
        elif kind == "string":
            hint = prop.get("hint")
            if prop.get("enum") is not None:
                span = f"one of {len(prop['enum'])} values"
                if hint:
                    span += f" ({hint})"
            else:
                span = str(hint or "text")
            parts.append(f"{name}: {span}")
        else:
            parts.append(f"{name}: {kind}")
    return "(" + ", ".join(parts) + ")" if parts else "()"


def planner_prompt(
    *,
    goal: str,
    goal_description: str,
    facts: Mapping[str, Any],
    library: Sequence[Mapping[str, Any]] = (),
    last_outcome: str = "",
) -> str:
    """The planner's brief.

    The library is included because Voyager's skill library is not a
    museum: a skill that already works is an option the planner may
    name, and a skill that failed last time is a warning.
    """
    lines = [
        f"GOAL: {goal}",
        f"WHAT THE GOAL MEANS: {goal_description}",
        "",
        "THE WORLD RIGHT NOW:",
        _facts_block(facts),
    ]
    if library:
        lines += ["", "SKILLS ALREADY IN THE LIBRARY:"]
        for skill in library:
            lines.append(
                f"  - {skill.get('id', '')}: {skill.get('title', '')} "
                f"({skill.get('description', '')})"
            )
    if last_outcome:
        lines += ["", "WHAT HAPPENED LAST TIME:", last_outcome]
    lines += [
        "",
        "Give the options and pick one.",
    ]
    return "\n".join(lines)


def coder_prompt(
    *,
    goal: str,
    goal_description: str,
    plan_description: str,
    facts: Mapping[str, Any],
    primitives: Mapping[str, Any],
    returns: Mapping[str, str] = (),
    previous_code: str = "",
    previous_error: str = "",
    critique: str = "",
    language: str = "javascript",
) -> str:
    """The coder's brief.

    The previous attempt and its error travel with the request: Voyager's
    second contribution is exactly this — the environment's feedback and
    the execution error go back into the next prompt, so the next program
    is not a guess but a revision.

    ``returns`` says what each primitive returns, as one short shape.
    A coder that has to guess treats a primitive as a boolean, and
    ``if (!mc.has(item))`` over the object it actually returns is a
    check that can never fire.
    """
    lines = [
        f"GOAL: {goal}",
        f"WHAT THE GOAL MEANS: {goal_description}",
        f"THE STEP TO TAKE: {plan_description}",
        "",
        "THE WORLD RIGHT NOW:",
        _facts_block(facts),
        "",
        "THE PRIMITIVES YOU MAY USE (and nothing else):",
    ]
    for name, schema in sorted(primitives.items()):
        line = f"  - {name}{_schema_signature(schema)}"
        if name in returns:
            line += f" -> {returns[name]}"
        lines.append(line)
    if previous_code:
        lines += [
            "",
            "YOUR PREVIOUS ATTEMPT (it did not work):",
            previous_code,
        ]
    if previous_error:
        lines += ["", "THE ERROR IT PRODUCED:", previous_error]
    if critique:
        lines += ["", "THE VERIFIER'S CRITIQUE OF THAT ATTEMPT:", critique]
    lines += [
        "",
        "Write the program.",
    ]
    return "\n".join(lines)


def verifier_prompt(
    *,
    goal: str,
    goal_description: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    log: Sequence[str] = (),
    self_verified: bool | None = None,
    ground_truth: bool | None = None,
    code: str = "",
) -> str:
    """The verifier's brief.

    The verifier sees the world before and after, the execution log, the
    model's own self-verification and the world's ground truth. The last
    two are given as *evidence*, not as the answer: the verifier is told
    what the environment said so it can weigh it, and it is free to
    answer INCONCLUSIVE.
    """
    lines = [
        f"GOAL: {goal}",
        f"WHAT THE GOAL MEANS: {goal_description}",
        "",
        "THE WORLD BEFORE:",
        _facts_block(before),
        "",
        "THE WORLD AFTER:",
        _facts_block(after),
    ]
    if code:
        lines += ["", "THE PROGRAM THAT RAN:", code]
    if log:
        lines += ["", "WHAT IT PRINTED:"]
        lines += [f"  {line}" for line in log]
    if self_verified is not None:
        lines += [
            "",
            "THE PROGRAM'S OWN CHECK SAID: "
            + ("the goal IS met" if self_verified else "the goal is NOT met"),
        ]
    if ground_truth is not None:
        lines += [
            "",
            "THE WORLD'S OWN RECORD SAYS: "
            + ("the goal IS met" if ground_truth else "the goal is NOT met"),
        ]
    lines += ["", "Answer CONFIRMED, DENIED or INCONCLUSIVE."]
    return "\n".join(lines)


def _brace_starts (text):
    """Where the balanced objects in the text begin."""
    starts = []
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                starts.append(index)
            depth += 1
        elif char == "}":
            if depth > 0:
                depth -= 1
    return starts


def parse_json_block (text: str) -> dict[str, Any]:
    """Read a JSON object out of a model's answer.

    Models fence their JSON and sometimes say a word before it, and a
    coder that shows a JavaScript object before its answer puts the
    answer second. So every balanced {...} in the reply is a candidate
    and the first one that is JSON is the answer.

    When there is none, it raises: a reply that cannot be read is not a
    reply, and guessing at it would put a fabrication into the log.
    """
    text = text.strip()
    if text.startswith("```"):
        # Drop a code fence, keeping the content.
        parts = text.split("```")
        for part in parts:
            candidate = part.strip()
            if candidate.startswith("json"):
                candidate = candidate[4:].strip()
            if candidate.startswith("{"):
                text = candidate
                break
    last_error = None
    for start in _brace_starts(text):
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : index + 1])
                    except ValueError as exc:
                        last_error = exc
                    break
    if last_error is not None:
        raise ValueError("no JSON object in the reply: " + str(last_error))
    raise ValueError("no JSON object in the reply")
