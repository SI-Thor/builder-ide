"""The seven-night melt run, as an executable session (plan item 13).

M2's first half is *"seven nights against the real owner or a simulated
one"* (`docs/plan.md` §2, week 3 item 13): the cold-start rules melt
mechanically — questions 6 → 0, `guess` → real claims per reason code as
denominators pass two, capability rows stop reading 0 — and the four
standing disciplines hold every night: capability rows and two-line
estimates in every morning, a standing exit in every branch set, the
decision budget enforced at the queue, and the attention cost falling.

This driver plays **seven evening → night → morning cycles** against the
**simulated owner** (`owner.py`: a fixed, seeded taste, stated as rules),
reusing the M1 driver's seats — the spine (`core-api`), the recipe store,
the vocabulary, the cold-start seat (whose gate and sealer *are* the melt),
and M1's stubs for the engine rungs, the scripted critic and the engineer.
Each step asserts its outcome and its budget and records what served it,
exactly as in M1; the run ends with the per-night table (G §1.9's melt
table, reproduced — or falsified — from the ledger alone).
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_M1 = _HERE.parent / "m1"
for _p in (str(_M1), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
# m1 is on the path first so its session modules (driver, session, budgets,
# seats/…) resolve; this directory's own module names exist nowhere there.

import driver as m1_driver  # noqa: E402  (M1's session script — its world is reused)
from budgets import (  # noqa: E402
    ASK_ANSWER_S, BRANCH_FLIP_S, COMPILE_S, DECISIONS_PER_MORNING,
    FIRST_LINE_S, KEEP_REJECT_S, PREFLIGHT_S, QUESTIONS_FIRST_SESSION,
    REPORT_FIRST_PAINT_S, SLATE_TRANSACTION_S, STOP_S,
)
from seats.coldstart import ColdOpenView  # noqa: E402
from seats.recipe import MAIN_BRANCH  # noqa: E402
from seats.stubs import stub_render  # noqa: E402
from session import Session, StepFailure, World  # noqa: E402
from spec_client import SpecError  # noqa: E402

import weekseat  # noqa: E402
from owner import (  # noqa: E402
    BANK_CODES, FLAW_CODES, OWNER, VALUE_TASTE, owner_table_is_a_taste,
)
from script import (  # noqa: E402
    ASK_CARDS, EXPECTED_QUESTIONS, NIGHT1_STRUCTURAL_DECISIONS, NIGHTS, NightSpec,
)

#: One night's rails — generous enough that the 80% bar never bites (the
#: week's cuts are the decision budget's, not the GPU bar's).
RAILS = {"gpu_minutes": 130.0, "hosted_cents": 0, "wall_minutes": 420.0}

#: The spine's four computed statuses (§3.4), spaced.
FOUR_STATUSES = ("ran as planned", "ran short", "ran degraded", "did not run")

ALL_CODES = tuple(BANK_CODES) + tuple(FLAW_CODES)
BUILDERS = ("companion", "architect", "prop-maker")


# --------------------------------------------------------------------------- setup


def build_week_world(home: Path, run_dir: Path) -> World:
    """M1's world (the spine and every seat, booted fresh) plus the week's
    own two long-lived pieces: one ask-mode ledger that persists across all
    seven sittings, and the melt's seal policy over it."""
    world = m1_driver.build_world(home, run_dir)
    asker = weekseat.WeekAsker(world.cold, world.door)
    world.asker = asker
    from core.coldstart import ColdStartSealer  # materialized by siblings.load()

    world.policy = ColdStartSealer(
        ledger=asker.ledger, clock=asker.clock,
        sealer=world.cold.stubs.PredictionSealer(ledger=asker.ledger,
                                                 clock=asker.clock),
    )
    world.week = {"nights": [], "melted_before": {}, "table": ""}
    return world


def teardown_week_world(world: World) -> None:
    m1_driver.teardown_world(world)


def _rec(world: World, n: int) -> dict:
    """The per-night record the melt table is built from."""
    records = world.week["nights"]
    while len(records) < n:
        records.append({"n": len(records) + 1})
    return records[n - 1]


def _w(value: str) -> str:
    return str(value or "").replace("_", " ").strip()


# ------------------------------------------------- the melt rule, restated


def spec_taste_decision(observed: int, kept: int) -> tuple[str, str, str]:
    """Decision 13a restated as the assertion's own statement — the seat's
    gate must agree with this, not the other way round.

    Below two observations: ask, and a sealed bet wears `guess` with the
    true count in its basis. At two: act, a real confidence with its
    denominator ("2/2 kept"); under three observations the confidence is
    `low` however good the ratio (T rule 3) — above that, ratio bands.
    """
    if observed < 2:
        basis = f"{observed} observation" if observed == 1 else f"{observed} observations"
        return ("ask", "guess", basis)
    ratio = kept / observed
    if observed < 3:
        confidence = "low"
    elif ratio >= 0.75:
        confidence = "high"
    elif ratio >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"
    return ("act", confidence, f"{kept}/{observed} kept")


def spec_world_decision(sealed: int, hits: int) -> tuple[str, str, str]:
    """The world axis, restated: `guess` is the zero-prior bet (spec §1.7);
    with any denominator the confidence follows the ratio rules, and acting
    alone needs the same two observations."""
    if sealed == 0:
        return ("ask", "guess", "0 observations")
    ratio = hits / sealed
    if sealed < 3:
        confidence = "low"
    elif ratio >= 0.75:
        confidence = "high"
    elif ratio >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"
    mode = "act" if sealed >= 2 else "ask"
    return (mode, confidence, f"{hits}/{sealed} hit")


# --------------------------------------------------------------------------- act 0


def act_week_boot(ses: Session, world: World) -> None:
    asker = world.asker

    with ses.step("owner-table", act="week",
                  backend="real:script(data)") as step:
        problems = owner_table_is_a_taste(world.cold.bank)
        step.check("every bank pair splits exactly one keep / one reject",
                   not problems, str(problems))
        kept_side = ", ".join(sorted(k for k, v in VALUE_TASTE.items() if v))
        step.note(f"the seeded taste keeps: {kept_side}")

    with ses.step("melt-baseline", act="week",
                  backend=["real:cold-start", "bridge:spine-ledger"]) as step:
        gate = asker.gate
        cold = all(gate.decide(b, code).observations == 0
                   for b in BUILDERS for code in ALL_CODES)
        step.check("evening one starts cold: 0 observations everywhere, "
                   "for every builder", cold, "the gate folds an empty ledger")
        spine = world.spec.taste(author="casey")
        rows = spine.get("notes", spine.get("rows", []))
        step.check("the spine's taste ledger is empty", len(rows) == 0,
                   f"{len(rows)} rows")


# --------------------------------------------------------------------------- act 1


def evening(ses: Session, world: World, spec_night: NightSpec) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe
    asker, S = world.asker, world.stamps
    n = spec_night.n
    rec = _rec(world, n)
    rec["date"] = spec_night.date

    # 1. the open line — a ledger read, instant by construction
    with ses.step(f"n{n}-open", act="evening", clock="Talk", budget=FIRST_LINE_S,
                  backend=["real:cold-start", "bridge:spine-ledger"]) as step:
        view = ColdOpenView(world.cold, world.door).line_and_starters()
        line = view["line"]
        if n == 1:
            step.check("night one opens on the zero denominator",
                       "0 of 0" in line, line)
        else:
            step.check("the return line carries its denominator (kept N of M)",
                       re.search(r"kept \d+ of \d+", line) is not None, line)
            step.check("and the denominator is no longer zero",
                       "0 of 0" not in line, line)
        step.check("no adjective about the owner",
                   all(word not in line.lower()
                       for word in ("great", "love", "always", "seem")),
                   line)
        step.check("one offer, of four seeds",
                   len(view["starters"]) == 4, str(view["starters"]))
        if n == 7:
            from core.coldstart import render_taste_claim

            claim = render_taste_claim(
                asker.gate, builder="companion", reason_code="too_clean",
                claim="You keep weathered wood over clean-sanded")
            step.check("evening seven's claim renders with its denominator "
                       "(the earned line, spine moment 2)",
                       claim.rendered and "2/2 kept" in claim.line,
                       claim.line or claim.refusal_reason or "")
            step.note(f"earned: {claim.line}")
        step.note(line)

    # 2. ask-mode: one sitting on the week's ledger — the melt decides what
    #    may still be asked (only codes below the asking builder's gate)
    with ses.step(f"n{n}-ask", act="evening", clock="Talk", budget=ASK_ANSWER_S,
                  backend=["real:cold-start", "bridge:spine-taste-ledger"]) as step:
        bank = world.cold.bank
        asker.new_sitting()
        asked, slowest, above_gate = 0, 0.0, []
        outcome = None
        while True:
            outcome = asker.ask_next(bank)
            if type(outcome).__name__ != "Asked":
                break
            question = outcome.question
            observed_before, _ = asker.observations("companion", question.reason_code)
            if observed_before >= 2:
                above_gate.append(question.reason_code)
            chip = OWNER.answer_chip(question)
            _, took = weekseat.timed(lambda: asker.answer(question, chip.id))
            slowest = max(slowest, took)
            asked += 1
        step.check(f"≤ {QUESTIONS_FIRST_SESSION} questions in the sitting",
                   asked <= QUESTIONS_FIRST_SESSION, f"asked {asked}")
        step.check("no question was asked above the two-observation gate",
                   not above_gate, str(above_gate))
        if n == 5:
            melted = set(getattr(outcome, "melted", ()) or ()) if outcome else set()
            step.check("asking is over: NothingToAsk, every bank code melted",
                       type(outcome).__name__ == "NothingToAsk"
                       and melted >= set(BANK_CODES),
                       f"{type(outcome).__name__}: {sorted(melted)}")
        seat_rows = asker.ledger.events(types=["taste.note.appended"])
        spine = spec.taste(author="casey")
        spine_rows = spine.get("notes", spine.get("rows", []))
        step.check("the two ledgers agree row for row",
                   len(spine_rows) == len(seat_rows),
                   f"spine {len(spine_rows)} vs seat {len(seat_rows)}")
        step.check(f"each answer ≤ {ASK_ANSWER_S:g} s (slowest measured)",
                   slowest <= ASK_ANSWER_S, f"{slowest * 1000:.1f} ms")
        rec["questions"] = asked
        stopped = type(outcome).__name__ if outcome else "?"
        step.note(f"{asked} asked · stopped: {stopped}")

    # 3. the slate: the night's bets as tasks with [e] asks, capability rows
    with ses.step(f"n{n}-slate", act="evening", clock="Workshop",
                  budget=SLATE_TRANSACTION_S, backend="real:core-api") as step:
        t0 = time.perf_counter()
        task1 = spec.file_task(
            f"N{n} · {spec_night.edit.message}",
            owner_character="prop-maker",
            recipe_scope=[spec_night.edit.word],
            cost_estimate={"gpu_minutes": 45.0, "wall_minutes": 60.0},
        )
        task2 = spec.file_task(
            f"N{n} · the world bet's run ({spec_night.world_bet.code})",
            owner_character="prop-maker",
            cost_estimate={"gpu_minutes": 30.0, "wall_minutes": 45.0},
        )
        card_tasks = []
        for i in range(spec_night.ask_cards):
            card = spec.file_task(
                f"Ask card {i + 1}: {ASK_CARDS[i][0]}",
                owner_character="companion",
                cost_estimate={"gpu_minutes": 1.0, "wall_minutes": 5.0},
            )
            card_tasks.append(card["task"]["id"])
        slate = spec.slate()
        elapsed = time.perf_counter() - t0
        step.check("the transaction fits the Workshop clock (X C13)",
                   elapsed <= SLATE_TRANSACTION_S, f"{elapsed * 1000:.1f} ms")
        step.check("the night's bets are slated",
                   len(slate["tasks"]) == 2 + spec_night.ask_cards,
                   str([t.get("intention") for t in slate["tasks"]]))
        expected_ask = 75.0 + 1.0 * spec_night.ask_cards
        step.check("the asks are marked fields ([e] until measured)",
                   slate["ask"]["gpu_minutes"] == expected_ask, str(slate["ask"]))
        step.check("the work-order line exists (X C11)",
                   "Work orders" in slate["work_order_line"],
                   slate["work_order_line"])
        step.check("one budget bar with counters",
                   {"gpu_minutes", "wall_minutes"} <= set(slate["bar"]),
                   str(slate["bar"]))
        step.check("money scoped to hosted calls reads $0.00 (local)",
                   "$0.00" in slate["money"], slate["money"])
        step.check("capability rows ride the slate (X C12)",
                   len(slate["capability_rows"]) == 3,
                   str([r["word"] for r in slate["capability_rows"]]))
        S[f"tasks_{n}"] = {"edit": task1["task"]["id"],
                           "world": task2["task"]["id"], "cards": card_tasks}

    # 4. the evening's one honest work order — both price lines, always
    with ses.step(f"n{n}-work-order", act="evening", clock="Workshop",
                  budget=COMPILE_S, backend="real:core-api") as step:
        result = spec.call(
            utterance=spec_night.wo.utterance,
            view={"branch": MAIN_BRANCH, "selection": [spec_night.edit.node]},
            intent={
                "title": spec_night.wo.title,
                "goal": spec_night.wo.goal,
                "estimate": spec_night.wo.estimate,
                "vocabulary_gap": {"word": spec_night.edit.word,
                                   "requested_by": "prop-maker"},
                "promote": _promote_entry(world, spec_night),
            },
        )
        step.check("one referent group compiles a draft (question XOR draft)",
                   "draft" in result and "question" not in result,
                   "question" if "question" in result else "draft")
        draft = result["draft"]
        line = draft["confirm_line"]
        step.check("the confirm carries the build/verify price line",
                   "build/verify" in line, line)
        step.check("and the generate/test price line — a one-line estimate "
                   "is a build failure (G §1 20:38)", "generate/test" in line, line)
        step.check("the order is reversible at a named version",
                   "reversible" in line.lower() or "ver_" in line, line)
        S[f"wo_{n}"] = draft["id"]
        confirmed = spec.confirm(draft["id"], answer="go", idem=f"week-n{n}-go")
        state = confirmed.get("state") or confirmed.get("work_order", {}).get("state")
        step.check("go → queued", state == "queued", str(state))
        if n == 1:  # the idempotency check, once
            again = spec.confirm(draft["id"], answer="go", idem="week-n1-go")
            confirms = door.raw_events(0, ["wo.confirmed"])
            step.check("a doubled Go is one Go (§5.3)",
                       len(confirms) == 1, f"{len(confirms)} wo.confirmed events")
        step.note(line)

    # 5. the handoff: pre-flight, lane free, queue counted
    with ses.step(f"n{n}-handoff", act="evening", clock="Watch",
                  budget=PREFLIGHT_S, backend="real:core-api") as step:
        started = spec.start_night(rails=RAILS, detach_after_min=30,
                                   load_budget={"stub-imagegen": 1},
                                   idem=f"week-n{n}-start")
        night = started["night"]
        line = started["preflight_line"]
        queue_n = 2 + spec_night.ask_cards
        step.check("the night is running", night["state"] == "running",
                   night["state"])
        step.check("the pre-flight names the lane", "lane free" in line, line)
        step.check("the pre-flight names the queue",
                   f"queue {queue_n} items" in line, line)
        step.check("the pre-flight names the detach rule", "detach" in line, line)
        step.check("proposes nothing when the lane is free",
                   started["preflight"]["proposals"] == [],
                   str(started["preflight"]))
        S[f"night{n}"] = night["id"]
        rec["night"] = night["id"]
        step.note(line)


def _promote_entry(world: World, spec_night: NightSpec) -> dict | None:
    """The v2 word a keep promotes (M1's crates-v2 shape, generalized)."""
    if not spec_night.wo.promote:
        return None
    base = next(e for e in world.seats.vocab.default_entries()
                if e.word == spec_night.wo.promote)
    doc = base.model_dump(mode="json")
    params = dict(doc["params"])
    props = dict(params.get("properties", {}))
    props.update(spec_night.wo.promote_props or {})
    params["properties"] = props
    return {**doc, "version": 2, "params": params,
            "provenance": {"origin": "wo", "at": "2026-10-30T21:10:00Z"}}


# --------------------------------------------------------------------------- act 2


def night(ses: Session, world: World, spec_night: NightSpec) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe
    asker, S = world.asker, world.stamps
    n = spec_night.n
    night_id = S[f"night{n}"]
    rec = _rec(world, n)
    seed = 100 + n

    # 1. the night's edit and its bets — the confidence is computed, never chosen
    with ses.step(f"n{n}-bets", act="night",
                  backend=["real:core-api", "real:core-recipe(seam)",
                           "real:cold-start(policy)", "bridge:spine-predictions",
                           "stub:render-rung", "stub:critic"]) as step:
        recipe.new_branch(alias=f"night{n}", name=f"night-{spec_night.date}",
                          purpose="night", spine_id=f"br_night{n}")
        door.publish_branch(f"br_night{n}", name=f"night-{spec_night.date}",
                            purpose="night", head=recipe.head(f"night{n}"))
        recipe.seam_branch = f"night{n}"
        call = spec.vocab_call(spec_night.edit.word, spec_night.edit.params,
                               node=spec_night.edit.node)
        step.check("the typed call committed through the recipe seam",
                   call.get("committed") is True, str(call.get("committed")))
        ver = call["version"]
        recipe.move_head(f"night{n}", ver)
        branch_ref = f"br_night{n}@{ver}"
        S[f"branch_ref_{n}"] = branch_ref
        render_spec = {"rung": 2, "resolution": "480p", "seed": seed}

        # the taste bets: the gate's decision, restated and asserted
        taste_seals = []
        for bet in spec_night.taste_bets:
            decision = asker.gate.decide("prop-maker", bet.code)
            expected = spec_taste_decision(decision.observations, decision.kept)
            step.check(
                f"{bet.code}: ask→act flips exactly as cold-start specifies",
                (decision.mode, decision.confidence, decision.basis) == expected,
                f"{decision.mode}/{decision.confidence}/{decision.basis} "
                f"vs {expected}")
            from core.coldstart import render_taste_claim

            claim = render_taste_claim(asker.gate, builder="prop-maker",
                                       reason_code=bet.code, claim=bet.claim)
            if decision.observations < 2:
                step.check("below two observations the claim does not render "
                           "(T rule 4 — no evidence, no claim)",
                           not claim.rendered
                           and claim.refusal_reason == "below_two_observations",
                           claim.refusal_reason or claim.line or "")
            else:
                step.check("at two the claim renders, uncertainty leading "
                           "(T rule 3)",
                           claim.rendered
                           and claim.line.startswith(decision.lead_clause),
                           claim.line or "")
            sealed = world.policy.seal_taste_bet(
                builder="prop-maker", reason_code=bet.code, claim=bet.claim,
                branch_ref=branch_ref, render_spec=render_spec)
            step.check("the seal carries the computed confidence and its basis",
                       sealed.confidence == decision.confidence
                       and sealed.basis == decision.basis,
                       f"{sealed.confidence} · {sealed.basis}")
            spine_seal = weekseat.mirror_seal(spec, sealed, branch_ref=branch_ref,
                                              render_spec=render_spec)
            taste_seals.append({
                "code": bet.code, "confidence": sealed.confidence,
                "basis": sealed.basis, "observations": decision.observations,
                "spine_id": spine_seal["prediction"]["id"],
                "seat_id": sealed.prediction.id,
            })

        # the world bet, on the same branch
        wd = asker.gate.decide_world("prop-maker", spec_night.world_bet.code)
        expected_world = spec_world_decision(wd.observations, wd.kept)
        step.check(
            f"{spec_night.world_bet.code} (world): the same rule on the world axis",
            (wd.mode, wd.confidence, wd.basis) == expected_world,
            f"{wd.mode}/{wd.confidence}/{wd.basis} vs {expected_world}")
        sealed_world = world.policy.seal_world_bet(
            builder="prop-maker", claim_type=spec_night.world_bet.code,
            claim=spec_night.world_bet.claim, branch_ref=branch_ref,
            render_spec=render_spec)
        spine_world = weekseat.mirror_seal(spec, sealed_world,
                                           branch_ref=branch_ref,
                                           render_spec=render_spec)
        world_pr = spine_world["prediction"]["id"]

        # seal strictly before the render job (§5.1, the standing gate)
        job = door.render_job(
            branch_ref=branch_ref,
            entry_paths=[".".join(spec_night.edit.word.split(".")[1:])],
            rung=2, seed=seed, prediction_id=world_pr, night=night_id,
            render=stub_render(seed, 2, f"night-{n}"))
        events = door.raw_events(0)
        seal_seq = next(int(e.seq) for e in events
                        if e.type == "prediction.sealed"
                        and e.payload.get("prediction", {}).get("id") == world_pr)
        enqueue_seq = next(int(e.seq) for e in events
                           if e.type == "job.enqueued"
                           and e.payload.get("prediction_id") == world_pr)
        step.check("sealed_at strictly before its render job's enqueue (§5.1)",
                   seal_seq < enqueue_seq, f"{seal_seq} < {enqueue_seq}")

        # the scripted critic — verdict@scripted on its face, timed for the box
        critic_word = spec_night.critic
        door.critic_verdict(
            job_id=job["job_id"], verdict=critic_word,
            code="reads_as_asked" if critic_word == "keep" else "wrong_scale",
            summary=(f"verdict@scripted · {spec_night.world_bet.claim[:60]} · "
                     f"{critic_word}"),
            extra={"timing": {"what": "scripted critic verdict",
                              "measured_ms": round(812.0 + n * 7.0, 1),
                              "label": "measured on the stub rung"}})
        scored = door.score_world_bet(world_pr, critic_word)
        expected_score = {"keep": "hit", "hold": "miss"}[critic_word]
        step.check("the critic scored the world bet — scored, never hidden",
                   scored.verdict == expected_score, scored.verdict)
        weekseat.mirror_score(asker, sealed_world.prediction.id, expected_score)

        # spend against the bar, and the load cap at its cap
        door.record_spend(night_id, {"gpu_minutes": 75.0, "wall_minutes": 105.0},
                          job=job["job_id"])
        door.model_load(night_id, "stub-imagegen")
        if n == 1:
            refused = None
            try:
                door.model_load(night_id, "stub-imagegen")
            except Exception as err:  # noqa: BLE001 — the cap's own refusal
                refused = err
            step.check("a second load of the same model is refused at admission "
                       "(§5.5)", refused is not None, str(refused)[:100])
        snap = spec.budget(night=night_id)
        step.check("the per-model load cap holds (1 of 1, at cap)",
                   snap["loads"].get("stub-imagegen") == 1
                   and snap["load_state"]["stub-imagegen"]["at_cap"],
                   str(snap["load_state"]))

        task_state = "kept" if critic_word == "keep" else "reverted"
        door.set_task_state(S[f"tasks_{n}"]["edit"], task_state,
                            reason=f"the night bet, {scored.verdict}")
        door.set_task_state(S[f"tasks_{n}"]["world"], task_state,
                            reason=f"the world bet, {scored.verdict}")
        rec["taste_seals"] = taste_seals
        rec["world_seal"] = {"code": spec_night.world_bet.code,
                             "confidence": sealed_world.confidence,
                             "basis": sealed_world.basis}
        rec["world_score"] = scored.verdict
        step.note(" · ".join(f"{t['code']}: {t['confidence']} ({t['basis']})"
                             for t in taste_seals)
                  + f" · world {sealed_world.confidence} ({sealed_world.basis})"
                  f" → {scored.verdict}")

    # 1b. mid-week: the melt re-derives from the ledger alone (the fold check)
    if n == 4:
        with ses.step("n4-gate-rebuild", act="night",
                      backend=["real:cold-start(fold)", "bridge:spine-ledger"]) as step:
            from core.coldstart import ColdStartGate

            rebuilt = ColdStartGate(asker.ledger)
            same = all(rebuilt.decide(b, code) == asker.gate.decide(b, code)
                       for b in BUILDERS for code in ALL_CODES)
            step.check("a rebuilt gate agrees on every builder × code "
                       "(the melt is a fold — kill -9 safe)", same,
                       "decisions re-derived from the ledger alone")

    # 2. the queue's two rules: the blocking dam, and the decision budget
    if spec_night.blocking_questions or spec_night.ask_cards:
        with ses.step(f"n{n}-queue-dam", act="night",
                      backend=["real:core-api", "bridge:queue-half"]) as step:
            for name in spec_night.blocking_questions:
                weekseat.park(spec, name, ["yes", "no"], blocking=True,
                              branch=f"br_night{n}")
            if spec_night.fourth_blocking:
                refused = None
                try:
                    weekseat.park(spec, "A fourth blocking question the dam refuses",
                                  ["a", "b"], blocking=True)
                except SpecError as err:
                    refused = err
                step.check("at most 3 blocking questions: the fourth is refused",
                           refused is not None and "park the task" in str(refused),
                           str(refused)[:110] if refused else "parked anyway")
                door.set_task_state(
                    S[f"tasks_{n}"]["world"], "parked",
                    reason=("would have needed a 4th blocking answer — the task "
                            "parked at the dam (spec §3.2.6)"))
                row = next(t for t in door.store.scan("tasks")
                           if t["id"] == S[f"tasks_{n}"]["world"])
                step.check("the parked task carries the one-line reason",
                           "4th blocking" in str(row["payload"].get("last_reason")),
                           str(row["payload"].get("last_reason")))
            if spec_night.ask_cards:
                cards = [{"name": name, "options": options, "task": task, "night": n}
                         for task, (name, options)
                         in zip(S[f"tasks_{n}"]["cards"], ASK_CARDS)]
                admission = weekseat.admit_ask_cards(
                    spec, door, cards=cards, night_id=night_id,
                    committed=NIGHT1_STRUCTURAL_DECISIONS)
                step.check(
                    f"the queue admitted {admission['room']} of 12 and cut the "
                    "rest at the budget", len(admission["admitted"]) == 5
                    and len(admission["cut"]) == 7,
                    f"admitted {len(admission['admitted'])}, cut {len(admission['cut'])}")
                open_q = [q for q in door.store.scan("questions") if q.get("open")]
                step.check("three blocking questions stand, five triaged non-blocking",
                           sum(1 for q in open_q if q.get("blocking")) == 3
                           and len(open_q) == 8, f"{len(open_q)} open")
                cut_rows = [t for t in door.store.scan("tasks")
                            if t.get("state") == "cut"
                            and t["payload"].get("night") == night_id]
                step.check("every cut task names the decision budget in its reason",
                           len(cut_rows) == 7
                           and all("decision budget"
                                   in str(t["payload"].get("last_reason"))
                                   for t in cut_rows),
                           f"{len(cut_rows)} cut tasks")
                rec["cut_tasks"] = len(cut_rows)

    if spec_night.parked_question:
        with ses.step(f"n{n}-parked-question", act="night",
                      backend="real:core-api") as step:
            parked = weekseat.park(spec, spec_night.parked_question,
                                   ["face the water", "face the shed wall"],
                                   blocking=True, branch=f"br_night{n}")
            S[f"parked_{n}"] = parked["question"]["id"]
            step.check("the question is parked open, two options, one tap",
                       len(parked["question"]["options"]) == 2
                       and parked["question"]["blocking"] is True,
                       parked["question"]["name"])

    if spec_night.assumes:
        with ses.step(f"n{n}-assumption", act="night",
                      backend="real:core-api") as step:
            door.event(
                "assumption.recorded", door.api.events.core_actor(),
                {"entity_kind": "question", "entity_id": f"q_assume_n{n}"},
                {"question": f"q_assume_n{n}",
                 "assumption": {"reading": "the conservative reading, taken at night",
                                "branch": f"br_night{n}", "night": n}})
            assumed = [e for e in door.raw_events(0, ["assumption.recorded"])
                       if e.payload.get("assumption", {}).get("branch")
                       == f"br_night{n}"]
            step.check("the assumption is recorded against the branch it replaced",
                       len(assumed) == 1, "assumption.recorded, attached")

    # 3. the work order's attempt: stub engineer, real gate, real land
    with ses.step(f"n{n}-wo-attempt", act="night",
                  backend=["real:core-api", "stub:engineer(aider-local)",
                           "stub:gate-engine"]) as step:
        wo_id = S[f"wo_{n}"]
        spend = {"gpu_minutes": 20.0, "wall_minutes": 90.0}
        patch = door.put_artifact(
            f"diff --git a/{spec_night.wo.title}\n+++ {spec_night.wo.goal}\n"
            .encode("utf-8"), f"wo-n{n}.patch")
        deliverable = {
            "attempt": "att_1",
            "commit": {"branch": f"wo/week-n{n}/1", "sha": f"a1c4e{n:02d}"},
            "code_diff": {"files": 2, "insertions": 30 + n, "deletions": 4,
                          "patch_ref": patch["sha256"]},
            "evidence": [
                {"kind": "test_run", "ref": "pytest", "sha256": patch["sha256"],
                 "summary": f"12 passed · {spec_night.wo.title}"},
                {"kind": "constraint_run", "ref": "analytic",
                 "sha256": patch["sha256"],
                 "summary": "analytic check at 2x (scripted, no physics engine)"},
            ],
            "budget_spend": spend,
            "notes": spec_night.wo.goal[:80],
        }
        door.record_spend(night_id, spend, job=wo_id)
        gate = door.run_engineer_attempt(
            wo_id, deliverable=deliverable,
            preview=stub_render(seed, 2, f"wo-n{n}"), night=None)
        step.check("the merge gate passed every check",
                   gate.get("passed") is True, str(gate.get("checks")))
        board = {w["id"]: w for w in spec.work_orders()}
        wo = board[wo_id]
        step.check("landed, with a preview before the owner is notified",
                   wo["state"] == "landed" and bool(wo.get("preview")), wo["state"])
        step.check("no card without an artifact (D)",
                   len(wo.get("evidence", [])) >= 2,
                   f"{len(wo.get('evidence', []))} evidence rows")

    # 4. heartbeats, then the kill switch — the status line is computed
    with ses.step(f"n{n}-stop", act="night", clock="Talk", budget=STOP_S,
                  backend="real:core-api") as step:
        for minutes, load in ((2, 0.2), (6, 0.4), (10, 0.3), (14, 0.3)):
            door.tick(night_id, at=_at_night(door, night_id, minutes), load=load)
        stopped = spec.stop_night(night_id, reason="morning", idem=f"week-n{n}-stop")
        state = stopped["night"]["state"] if "night" in stopped else stopped.get("state")
        step.check("the night stopped cleanly", state == "stopped", str(state))
        status = door._svc("nights").compute_status(night_id)
        expected_status = "ran short" if spec_night.ask_cards else "ran degraded"
        step.check(f"the status line is computed: {expected_status} "
                   "(the cut named / the scripted-only verdicts named)",
                   _w(status.get("status")) == expected_status, status.get("line", ""))
        step.check("and it is one of the four (§3.4)",
                   _w(status.get("status")) in FOUR_STATUSES, str(status))
        rec["status"] = _w(status.get("status"))
        rec["status_line"] = status.get("line", "")
        step.note(status.get("line", ""))


def _at_night(door, night_id: str, minutes: int) -> str:
    from datetime import datetime, timedelta

    started = next(
        (e.payload.get("night", {}).get("started_at") or e.at
         for e in door.raw_events(0, ["night.started"])
         if e.subject.get("entity_id") == night_id), None)
    moment = datetime.fromisoformat(started.replace("Z", "+00:00")) + timedelta(
        minutes=minutes)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- act 3


def morning(ses: Session, world: World, spec_night: NightSpec) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe
    asker, S = world.asker, world.stamps
    n = spec_night.n
    night_id = S[f"night{n}"]
    rec = _rec(world, n)
    seq_before = door.store.max_seq()

    # 1. the report opens — before the world
    with ses.step(f"n{n}-report", act="morning", clock="Watch",
                  budget=REPORT_FIRST_PAINT_S, backend="real:core-api") as step:
        t0 = time.perf_counter()
        doc = spec.report(night_id, mode="json")["report"]
        step.check("first paint ≤ 3 s (a static page over the ledger)",
                   time.perf_counter() - t0 <= REPORT_FIRST_PAINT_S,
                   f"{(time.perf_counter() - t0) * 1000:.1f} ms")
        status = doc["status_line"]
        step.check("the computed status leads",
                   _w(status.get("status")) == rec["status"], str(status))
        step.check("the failure line is always present",
                   isinstance(doc["failure_line"], str) and doc["failure_line"],
                   doc["failure_line"])
        if spec_night.ask_cards:
            cut = doc["cut"]
            step.check("the cut is named where it happened — the queue",
                       any("Ask card" in str(t.get("intention")) for t in cut["tasks"]),
                       cut["line"])
            step.check("the cut rows carry the decision budget as their reason",
                       any("decision budget" in str(t.get("last_reason"))
                           for t in cut["tasks"]), "")
            pq = doc["parked_questions"]
            step.check("parked questions triaged top-3 plus a count of the rest",
                       len(pq["top_3"]) == 3 and pq["count"] == 8
                       and "5 more, none blocking" in pq["more_line"],
                       f"{pq['count']} open · {pq['more_line']}")
        numbers = doc["night_numbers"]
        step.check("the numbers carry the load count against its cap",
                   "loads (budget" in numbers["line"], numbers["line"])
        step.check("the box replaced the slate's [e] with the night's measurements",
                   len(doc["the_box"]) >= 1, str(doc["the_box"][:1]))
        tally = doc["tally"]
        step.check("the tally carries denominators per builder × claim type",
                   bool(tally) and all(r["denominator"] >= 1 for r in tally),
                   str([(r["claim_type"], r["denominator"]) for r in tally]))
        if n == 1:
            step.check("night one's tally says the empty thing (G §1 07:12)",
                       any("not taste yet" in r["line"] for r in tally),
                       str([r["line"] for r in tally]))
        step.check("no single prediction score anywhere (X C2)",
                   "prediction score" not in str(doc).lower(), "")
        text = spec.report(night_id, mode="text")
        step.check("the text mode is the same ledger read",
                   _w(rec["status"]).replace(" ", " ") in text.replace("_", " "),
                   text.splitlines()[2] if len(text.splitlines()) > 2 else text[:60])
        three = doc["three_number_line"]
        step.check("the three-number line names the attention budget",
                   three.get("attention_budget") == DECISIONS_PER_MORNING,
                   three.get("line", ""))
        rec["tally_line"] = " | ".join(r["line"] for r in tally)
        S[f"report_{n}"] = doc
        step.note(f"{doc['failure_line']} · {three.get('line', '')}")

    # 2. the branch set: the night's option plus the two standing exits
    with ses.step(f"n{n}-branches", act="morning", clock="Watch",
                  budget=BRANCH_FLIP_S,
                  backend=["real:core-api", "real:core-recipe(seam)"]) as step:
        door.publish_branch(f"br_night{n}", name=f"night-{spec_night.date}",
                            purpose="morning-option",
                            head=recipe.head(f"night{n}"),
                            base=recipe.head(MAIN_BRANCH))
        out = spec.branches()
        standing = [s["name"] for s in out["standing"]]
        step.check("the two standing exits are present — every morning (X G7)",
                   any("keep yesterday" in nm for nm in standing)
                   and any("back to the plan" in nm for nm in standing),
                   str(standing))
        doc_standing = S[f"report_{n}"]["branches"]["standing"]
        step.check("and in the report's branch set",
                   any("keep yesterday" in s["name"] for s in doc_standing)
                   and any("back to the plan" in s["name"] for s in doc_standing),
                   str([s["name"] for s in doc_standing]))
        names = {b["id"] for b in out["branches"]}
        step.check("the night's option is on the board",
                   f"br_night{n}" in names, str(sorted(names)))
        t0 = time.perf_counter()
        spec.branches()
        flip = time.perf_counter() - t0
        step.check(f"the flip (a pointer move) ≤ {BRANCH_FLIP_S:g} s",
                   flip <= BRANCH_FLIP_S, f"{flip * 1000:.1f} ms")
        rec["standing"] = True

    # 3. the owner decides — by rule; every decision is one tap
    with ses.step(f"n{n}-decide", act="morning", clock="Talk",
                  budget=KEEP_REJECT_S,
                  backend=["real:core-api", "bridge:apply-scores-taste",
                           "decision"]) as step:
        choice = OWNER.branch_choice(spec_night.edit.value)
        if choice == "apply":
            applied = spec.apply_branch(f"br_night{n}")
            step.check("apply is a head move, the store following",
                       applied.get("branch") == f"br_night{n}"
                       and applied.get("recipe_sync") == "ok", str(applied))
            recipe.move_head(MAIN_BRANCH, recipe.head(f"night{n}"))
            door.publish_nodes(
                MAIN_BRANCH,
                recipe.derived_nodes(recipe.refresh_recipe(recipe.head(f"night{n}"))),
                head=recipe.head(f"night{n}"))
        else:
            main_before = recipe.head(MAIN_BRANCH)
            door.event("branch.rejected", door.api.events.owner_actor("casey"),
                       {"entity_kind": "branch", "entity_id": f"br_night{n}"},
                       {"retained": True, "by": "owner",
                        "note": "keep yesterday — the standing exit, taken as a choice"})
            step.check("keep yesterday: the standing exit, and main never moved",
                       recipe.head(MAIN_BRANCH) == main_before,
                       "the night's option stays visitable, rejected not deleted")
        scored = weekseat.score_taste_bets(
            door, f"br_night{n}", OWNER.taste_bet_outcome(spec_night.edit.value))
        step.check("the owner's ruling scored the night's taste bets (§1.7)",
                   len(scored) == len(spec_night.taste_bets),
                   f"{len(scored)} of {len(spec_night.taste_bets)}")
        bet_verdict = {"keep": "hit", "reject": "miss"}[
            OWNER.taste_bet_outcome(spec_night.edit.value)]
        for seal in rec.get("taste_seals", []):
            weekseat.mirror_score(asker, seal["seat_id"], bet_verdict)
        rec["branch_choice"] = choice

        wo_verdict = OWNER.artifact_verdict(spec_night.wo.value)
        if wo_verdict == "keep":
            kept = spec.keep(S[f"wo_{n}"], idem=f"week-n{n}-keep")
            if spec_night.wo.promote:
                promotion = kept.get("promotion")
                step.check("keep promoted the word — the growth beat (§2.3)",
                           promotion and promotion.get("word") == spec_night.wo.promote
                           and promotion.get("status") == "active", str(promotion))
                words = {w["word"]: w for w in spec.vocab()["words"]}
                gained = next(iter(spec_night.wo.promote_props or {}), None)
                step.check(f"the word is active and gained {gained}",
                           words[spec_night.wo.promote]["status"] == "active"
                           and gained in words[spec_night.wo.promote]["params"]
                           .get("properties", {}),
                           words[spec_night.wo.promote]["status"])
        else:
            weekseat.reject_work_order(spec, S[f"wo_{n}"], idem=f"week-n{n}-reject")
            board = {w["id"]: w for w in spec.work_orders()}
            step.check("the reject retains the branch; the word is not promoted",
                       board[S[f"wo_{n}"]]["state"] == "rejected",
                       board[S[f"wo_{n}"]]["state"])
        rec["wo_verdict"] = wo_verdict

        # the parked questions, answered in one tap each (rule 6)
        if spec_night.ask_cards:
            open_q = sorted((q for q in door.store.scan("questions") if q.get("open")),
                            key=lambda q: q["id"])
            for q in open_q:
                spec.answer_question(q["id"], q["payload"]["options"][0],
                                     idem=f"week-n{n}-answer-{q['id']}")
            step.check(f"the {len(open_q)} parked questions answered in one tap each",
                       len(open_q) == 8, f"{len(open_q)} answered")
        if spec_night.parked_question:
            spec.answer_question(S[f"parked_{n}"], "face the water",
                                 idem=f"week-n{n}-parked-answer")
            answered_events = [
                e for e in door.raw_events(0, ["question.answered"])
                if e.subject.get("entity_id") == S[f"parked_{n}"]]
            step.check("the night's parked question answered in one tap",
                       len(answered_events) == 1, "one question.answered event")

        # the unprompted verdict — the row that melts every builder
        row = weekseat.unprompted_row(
            asker, door, code=spec_night.flaw,
            verdict=OWNER.artifact_verdict(spec_night.edit.value),
            artifact_ref=S[f"branch_ref_{n}"],
            param_path=spec_night.edit.word, value=spec_night.edit.value)
        spine = spec.taste(author="casey")
        spine_rows = spine.get("notes", spine.get("rows", []))
        seat_rows = asker.ledger.events(types=["taste.note.appended"])
        step.check("the unprompted row landed on both ledgers",
                   len(spine_rows) == len(seat_rows),
                   f"spine {len(spine_rows)} vs seat {len(seat_rows)}")
        step.note(f"branch: {choice} · work order: {wo_verdict} · "
                  f"flaw row: {spec_night.flaw}/"
                  f"{OWNER.artifact_verdict(spec_night.edit.value)}")

    # 4. capability rows and two-line estimates — in every morning
    with ses.step(f"n{n}-capability-and-estimates", act="morning",
                  backend="real:core-api") as step:
        slate = spec.slate()
        rows = {r["word"]: r for r in slate["capability_rows"]}
        step.check("capability rows are present in the morning", len(rows) == 3,
                   str(sorted(rows)))
        if n == 1:
            step.check("night one's rows read their zero denominators",
                       all(r["calls"] == 0 for r in rows.values()),
                       str({w: r["calls"] for w, r in rows.items()}))
            step.check("the crates row was reset by its own promotion — a drift, "
                       "named (X C12)", rows["props.harbor.crates"]["calls"] == 0,
                       "promotion overwrites the row; the count restarts")
        else:
            nonzero = [w for w, r in rows.items() if r["calls"] >= 1]
            step.check("capability rows stopped reading 0 (the melt's other half)",
                       len(nonzero) >= 1,
                       str({w: r["calls"] for w, r in rows.items()}))
        board = spec.work_orders()
        step.check("every order the morning reads carries both price lines (X R16)",
                   all("build/verify" in w["confirm_line"]
                       and "generate/test" in w["confirm_line"] for w in board),
                   f"{len(board)} orders")
        landed = S[f"report_{n}"]["landed_work_orders"]
        step.check("the landed order's estimate carries both halves",
                   bool(landed)
                   and all(w.get("estimate", {}).get("build_verify")
                           and w["estimate"].get("generate_test") for w in landed),
                   f"{len(landed)} landed")
        rec["capability"] = {w: r["calls"] for w, r in rows.items()}

    # 5. the attention number — decisions this morning asked of the owner
    with ses.step(f"n{n}-attention", act="morning",
                  backend="real:core-api") as step:
        decisions = weekseat.decisions_since(door, seq_before)
        step.check(f"the morning asked ≤ {DECISIONS_PER_MORNING} decisions "
                   "(G §4.3 — the queue did the cutting)",
                   len(decisions) <= DECISIONS_PER_MORNING,
                   f"{len(decisions)}: {[d['type'] for d in decisions]}")
        if spec_night.ask_cards:
            step.check("night one sat exactly at the budget — never over it",
                       len(decisions) == DECISIONS_PER_MORNING,
                       f"{len(decisions)} decisions")
        rec["decisions"] = len(decisions)
        rec["attention"] = rec.get("questions", 0) + len(decisions)
        three = S[f"report_{n}"]["three_number_line"]
        step.note(f"{three.get('line', '')} · this morning: {len(decisions)} · "
                  f"the evening asked {rec.get('questions', 0)}")


# --------------------------------------------------------------------------- the week


def _melted_snapshot(world: World) -> dict:
    gate = world.asker.gate
    return {b: set(gate.melted_codes(b)) for b in BUILDERS}


def the_week_table(ses: Session, world: World) -> str:
    """The week-level checks, then G §1.9's table reproduced from the ledger."""
    spec, door, asker = world.spec, world.door, world.asker
    records = world.week["nights"]

    with ses.step("melt-table", act="week", backend="ledger-fold") as step:
        qs = [r.get("questions", 0) for r in records]
        step.check("questions fell exactly as the mechanism says "
                   "(G §1.9's table, reproduced)", qs == list(EXPECTED_QUESTIONS),
                   str(qs))
        step.check("and hit zero by evening five, staying there",
                   qs[4:] == [0, 0, 0] and qs[0] > 0, str(qs))

        # every guess sat below the gate; no code sealed guess past two
        guesses, claims = [], []
        for r in records:
            for t in r.get("taste_seals", []):
                (guesses if t["confidence"] == "guess" else claims).append(
                    (r["n"], t["code"], t["observations"]))
        step.check("every sealed guess sat below the two-observation gate",
                   all(obs < 2 for _, _, obs in guesses), str(guesses))
        step.check("no taste bet sealed guess once its code held two "
                   "observations — guesses → gone, per code",
                   all(obs >= 2 for _, _, obs in claims), str(claims))
        wrong_material = [(r["n"], t["confidence"])
                          for r in records for t in r.get("taste_seals", [])
                          if t["code"] == "wrong_material"]
        too_busy = [(r["n"], t["confidence"], t["observations"])
                    for r in records for t in r.get("taste_seals", [])
                    if t["code"] == "too_busy"]
        # per builder: the asked track melts the asker; the unprompted track
        # melts everyone; the architect was never asked
        gate = asker.gate
        step.check("one code across the week: guess → guess (1 obs) → claim "
                   "at two, exactly (G §1.9's nights 1–3)",
                   [(n, c) for n, c, _ in too_busy]
                   == [(1, "guess"), (2, "guess"), (3, "low")],
                   str(too_busy))
        step.check("and a code nobody fed stayed a guess — the gate held all "
                   "week (no observations, no claim)",
                   wrong_material == [(1, "guess")]
                   and gate.decide("prop-maker", "wrong_material").mode == "ask",
                   str(wrong_material))
        step.check("the companion melted all eight bank codes",
                   set(BANK_CODES) <= gate.melted_codes("companion"),
                   str(sorted(gate.melted_codes("companion"))))
        step.check("the architect melted no bank code — nobody asked it",
                   not (set(BANK_CODES) & gate.melted_codes("architect")),
                   str(sorted(gate.melted_codes("architect"))))
        step.check("every builder melted the unprompted codes (the owner's "
                   "keeps count for all)",
                   all(code in gate.melted_codes(b)
                       for b in BUILDERS
                       for code in ("too_busy", "too_messy", "too_dark")),
                   str({b: sorted(gate.melted_codes(b)) for b in BUILDERS}))
        step.check("no_focus never reached two — it still asks, honestly",
                   all(gate.decide(b, "no_focus").mode == "ask" for b in BUILDERS),
                   "one observation, all week")

        # the melt is visible in the spine's ledger, code for code
        spine = spec.taste(author="casey")
        spine_rows = spine.get("notes", spine.get("rows", []))
        spine_codes: dict[str, int] = {}
        for row in spine_rows:
            spine_codes[row["reason_code"]] = spine_codes.get(row["reason_code"], 0) + 1
        from collections import Counter

        seat_codes = dict(Counter(
            e.payload["row"]["reason_code"]
            for e in asker.ledger.events(types=["taste.note.appended"])))
        step.check("the spine's ledger carries the melt, code for code",
                   spine_codes == seat_codes,
                   f"spine {spine_codes} vs seat {seat_codes}")

        # attention and the decision budget
        att = [r.get("attention", 0) for r in records]
        dec = [r.get("decisions", 0) for r in records]
        step.check("no morning exceeded the decision budget — the queue cut "
                   "instead (G §7 test 9)", all(d <= DECISIONS_PER_MORNING for d in dec),
                   str(dec))
        step.check("the attention cost fell across the week (plan §6)",
                   att[0] > att[1] > att[2]
                   and all(att[i] >= att[i + 1] for i in range(2, 6))
                   and att[-1] < att[0], str(att))
        step.check("every morning offered both standing exits (G §7 test 10)",
                   all(r.get("standing") for r in records), "")
        step.check("every status line was computed, one of the four",
                   all(r.get("status") in FOUR_STATUSES for r in records),
                   str([r.get("status") for r in records]))

    return render_melt_table(world)


def render_melt_table(world: World) -> str:
    records = world.week["nights"]
    head = (f"{'NIGHT':<6}{'EVE-QS':>7}  {'TASTE BETS SEALED AS':<40}"
            f"{'WORLD BET':<24}{'STATUS':<13}{'DEC':>4}{'ATT':>5}")
    lines = [head, "-" * len(head)]
    for r in records:
        taste = " + ".join(f"{t['confidence']}·{t['basis'].replace(' observations', ' obs')}"
                           for t in r.get("taste_seals", [])) or "—"
        world_bet = r.get("world_seal", {})
        world_s = (f"{world_bet.get('confidence')}·"
                   f"{world_bet.get('basis', '').replace(' observations', ' obs')} "
                   f"→ {r.get('world_score', '')}")
        lines.append(
            f"{r['n']:<6}{r.get('questions', 0):>7}  {taste:<40}{world_s:<24}"
            f"{r.get('status', ''):<13}{r.get('decisions', 0):>4}"
            f"{r.get('attention', 0):>5}")
    lines.append("")
    lines.append("what melted each night (folded from the ledger at the morning):")
    previous: dict[str, set] = {}
    for r in records:
        melted = r.get("melted_after", {})
        newly = {}
        for builder, codes in melted.items():
            diff = codes - previous.get(builder, set())
            if diff:
                newly[builder] = sorted(diff)
            previous[builder] = codes
        if newly:
            who = "; ".join(f"{b}: {', '.join(c)}" for b, c in sorted(newly.items()))
        else:
            who = "nothing — the emptiness is shown" if r["n"] == 1 else "nothing new"
        lines.append(f"  night {r['n']} ({r.get('date', '')}): {who}")
    lines.append("")
    lines.append("the tally each morning read (denominators, never a score):")
    for r in records:
        lines.append(f"  night {r['n']}: {r.get('tally_line', '')}")
    lines.append("")
    lines.append("the branch each morning took: "
                 + ", ".join(f"n{r['n']}={r.get('branch_choice', '?')}"
                             for r in records))
    return "\n".join(lines)


def _record_melt_state(world: World, n: int) -> None:
    _rec(world, n)["melted_after"] = _melted_snapshot(world)


# --------------------------------------------------------------------------- the play


def play_week(world: World, ses: Session | None = None) -> Session:
    """Play the seven cycles; the first failed step raises StepFailure."""
    ses = ses or Session(world)
    try:
        m1_driver.act_boot(ses, world)
        act_week_boot(ses, world)
        for spec_night in NIGHTS:
            evening(ses, world, spec_night)
            night(ses, world, spec_night)
            morning(ses, world, spec_night)
            _record_melt_state(world, spec_night.n)
        world.week["table"] = the_week_table(ses, world)
    finally:
        world.artifacts["steps"] = ses.steps
    return ses


def main() -> int:
    """The headless driver: run the week, print the step table and the melt table."""
    import tempfile

    run_dir = _HERE / "run" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="week-home-") as tmp:
        world = build_week_world(Path(tmp) / "builder-ide", run_dir)
        ses = Session(world)
        try:
            play_week(world, ses)
        except StepFailure as failure:
            out = ses.table() + "\n\n" + world.week.get("table", "")
            print(out)
            print(f"\nFAILED: {failure}")
            (run_dir / "steps.txt").write_text(out + f"\n\nFAILED: {failure}\n")
            teardown_week_world(world)
            return 1
        out = ses.table() + "\n\n" + world.week["table"]
        print(out)
        print(f"\nSeven nights played end to end: {len(ses.steps)} steps, "
              f"{sum(1 for s in ses.steps if s.ok)}/{len(ses.steps)} passed.")
        (run_dir / "steps.txt").write_text(out + "\n")
        teardown_week_world(world)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
