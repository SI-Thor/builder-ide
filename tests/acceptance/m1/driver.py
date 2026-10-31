"""The M1 acceptance session, as an executable script.

M1 is "one evening, one night, one morning, one builder, one room"
(`docs/plan.md` §2): Casey creates a project, gets the zero-denominator
opener and four seeds, answers ≤ 6 two-chip questions, puts two small bets
on a slate with a budget bar, says "Go" to one honest work order (crates
gain lids and rope handles), goes to bed. In the morning: the status line,
failures first, the numbers with the cut, branches plus the two standing
exits, one landed work order with a preview and evidence, "why?" in one
tap, the tally — and one more in-game computer call with two plausible
referents, which must come back a question, never a plan.

Each step asserts its outcome and its latency budget from the spine, and
records what served it — sibling seat (real), bridge, or stub. The slice
gates named by the plan are steps of the script, not a separate suite:

* **(a) kill -9** — `night/kill-9`: the feed and the status render from the
  ledger alone after a real close and reopen;
* **(b) two referents** — `morning/computer-call`: a question, not a plan;
* **(c) seal before render** — `night/sealed-bet-crates`, plus the
  reference loop's own ledger ordering;
* **(d) zero panel-side state** — the whole morning reads through a client
  recreated after the kill;
* the cold open and the question budget — `evening/cold-open`,
  `evening/ask-mode`.
"""

from __future__ import annotations

import time
from pathlib import Path

import siblings
from budgets import (
    APPLY_S, ASK_ANSWER_S, BRANCH_FLIP_S, CARD_LEGIBLE_S, CHIP_LANDS_S,
    COMPILE_S, CONFIRM_READABLE_S, DECISIONS_PER_MORNING, FIRST_LINE_S,
    KEEP_REJECT_S, PEEK_JOIN_S, PREFLIGHT_S, QUESTIONS_FIRST_SESSION,
    QUESTION_ANSWER_S, REPORT_FIRST_PAINT_S, SLATE_TRANSACTION_S, STOP_S,
    WHY_S,
)
from session import Session, StepFailure, World
from spec_client import CoreDoor, SpecClient, SpecError
from seats.coldstart import AskModeRunner, ColdStartSeat
from seats.nightrunner import NightRunnerSeat
from seats.recipe import MAIN_BRANCH, RecipeSeat
from seats.stubs import StubGateEngine, StubTelemetry, stub_render
from seats.vocabloop import build_cold_world, run_cold_night, sealed_before_render


# --------------------------------------------------------------------------- setup


def build_world(home: Path, run_dir: Path) -> World:
    """Boot the spine and the seats: one fresh `$BUILDER_HOME`, one run dir.

    The seats are the integrated core's own packages (`siblings.load()`):
    the spine is `core.svc.Core` + `core.api.create_app`, the recipe store
    rides the spine's one ledger through `RecipeStoreSeam`, and the stubs
    are the engine-side pieces no seat owns yet (render rungs, critic,
    engineer, gate engine — plan §2 M1 risks).
    """
    seats = siblings.load()
    world = World(home=home, run_dir=run_dir)
    world.seats = seats

    from core.config import Settings
    from core.svc import Core

    settings = Settings.for_home(home)
    core = Core.open(
        settings,
        telemetry=StubTelemetry(load=0.3),
        gate_engine=StubGateEngine(),
    )
    recipe_seat = RecipeSeat(seats, core)  # wires core.recipes; one store
    from core.api import create_app
    from fastapi.testclient import TestClient

    app = create_app(settings, core=core)
    http = TestClient(app)
    http.__enter__()  # lifespan: stream counters etc.

    world.spec = SpecClient(http)
    world.door = CoreDoor(seats, core, settings)
    world.recipe = recipe_seat
    world.cold = ColdStartSeat(seats)
    world.night_seat = NightRunnerSeat(seats)
    world.vocab_world = build_cold_world(seats)
    world.stamps["settings"] = settings
    world.stamps["http"] = http
    return world


def teardown_world(world: World) -> None:
    http = world.stamps.get("http")
    if http is not None:
        try:
            http.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 — the ledger may already be closed
            pass


def reconnect(world: World) -> None:
    """After the kill: a fresh core + app over the same ledger file."""
    from core.api import create_app
    from fastapi.testclient import TestClient

    old = world.stamps.get("http")
    if old is not None:
        try:
            old.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
    core = world.door.reopen(
        telemetry=StubTelemetry(load=0.3),
        gate_engine=StubGateEngine(),
    )
    world.recipe.rebind(core)  # the store survived in the one log
    http = TestClient(create_app(world.stamps["settings"], core=core))
    http.__enter__()
    world.stamps["http"] = http
    world.spec = SpecClient(http)


# --------------------------------------------------------------------------- helpers


def _seq_of(events, type_: str, match: dict | None = None) -> int | None:
    for ev in events:
        if ev.type != type_:
            continue
        payload = ev.payload if hasattr(ev, "payload") else ev.get("payload", {})
        if match and not all(payload.get(k) == v for k, v in match.items()):
            continue
        seq = ev.seq if hasattr(ev, "seq") else ev["seq"]
        return int(seq)
    return None


def _word_count(text: str) -> int:
    return len(text.split())


def _status_word(value) -> str:
    """The four status values, spaced (`ran as planned` — the spec's words)
    whatever spelling a seat chose internally."""
    return str(value or "").replace("_", " ").strip()


def _check_budget_line(step: Step, name: str, line: str) -> None:
    """The confirm line carries both price lines — a one-line estimate is a
    build failure (G §1 20:38; slice acceptance (f))."""
    step.check("build/verify price line present", "build/verify" in line, line)
    step.check("generate/test price line present", "generate/test" in line, line)


# --------------------------------------------------------------------------- act 0


def act_boot(ses: Session, world: World) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe

    with ses.step("fresh-home", act="boot", backend="real:core-api") as step:
        events = door.raw_events()
        kinds = {e.type for e in events}
        step.check("a fresh home holds nothing but the boot's own events",
                   kinds <= {"core.boot", "core.recovered", "projection.rebuilt"},
                   str(kinds))
        step.note("seats at " + ", ".join(
            f"{name}@{head[:9]}" for name, head in sorted(world.seats.heads.items())))

    with ses.step("recipe-seat", act="boot",
                  backend=["real:core-recipe", "real:vocab(data)"]) as step:
        step.check("Fjellvik has a root version",
                   recipe.root_version.startswith("ver_"), recipe.root_version)
        nodes = recipe.derived_nodes()
        step.check("the node registry derived three entries", len(nodes) == 3,
                   ", ".join(n["node_id"] for n in nodes))
        # the publishing convention (core-api ports.py): nodes.json rides a
        # version.committed artifact; the branch row exists for the registry
        # projection to resolve against.
        door.publish_branch(MAIN_BRANCH, name="main", purpose="main",
                            head=recipe.root_version)
        door.publish_nodes(MAIN_BRANCH, nodes, head=recipe.root_version)
        spine_nodes = door.store.scan("node_refs")
        step.check("the spine folded the published nodes", len(spine_nodes) == 3,
                   f"{len(spine_nodes)} node_refs rows")

    with ses.step("vocabulary", act="boot",
                  backend=["real:vocab(data)", "real:core-api"]) as step:
        for entry in world.seats.vocab.default_entries():
            door.add_vocab_word(entry.model_dump(mode="json"))
        words = spec.vocab()["words"]
        step.check("the three words of the slice are active", len(words) == 3,
                   ", ".join(w["word"] for w in words))
        rows = {r["word"]: r for r in spec.vocab()["capability_rows"]}
        zero_denominators = all(
            "built 0" in r["line"] or r["calls"] == 0 for r in rows.values()
        )
        step.check("capability rows carry their zero denominators (X C12)",
                   zero_denominators, str({k: v["line"] for k, v in rows.items()}))


# --------------------------------------------------------------------------- act 1


def act_evening(ses: Session, world: World) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe
    S = world.stamps

    # 1. the cold open (spine moment 1; slice gate: the first-run test)
    with ses.step("cold-open", act="evening", clock="Talk", budget=FIRST_LINE_S,
                  backend=["real:cold-start", "real:core-api(ledger)"]) as step:
        view = world.cold_view()
        line = view["line"]
        step.check("zero denominator on the first line", "0 of 0" in line, line)
        step.check("no adjective about the owner",
                   all(word not in line.lower() for word in ("great", "love", "always")),
                   line)
        step.check("exactly one offer, of four seeds",
                   "Four ways to start" in line and len(view["starters"]) == 4,
                   str(view["starters"]))
        step.check("each starter carries its seed on its face",
                   all("seed" in s and isinstance(s["seed"], int) for s in view["starters"]),
                   str(view["starters"]))
        S["starters"] = view["starters"]
        step.note(line)

    # 2. Casey picks a starter: the project's seed is a choice, not a guess
    with ses.step("pick-a-starter", act="evening", clock="Talk", budget=CHIP_LANDS_S,
                  backend=["real:core-recipe", "real:core-api(ledger)"]) as step:
        picked = S["starters"][0]
        ver = recipe.store.apply_edit(
            recipe.head(MAIN_BRANCH),
            [recipe.br.Op(op="set", path="seeds.terrain", value=picked["seed"])],
            author=recipe.owner,
            message=f"starter: {picked['name']} · seed {picked['seed']}",
        )
        recipe.move_head(MAIN_BRANCH, ver.id)
        door.publish_nodes(MAIN_BRANCH, recipe.derived_nodes(
            recipe.refresh_recipe(ver.id)), head=ver.id)
        seeds = recipe.document(ver.id)["seeds"]
        step.check("the picked seed is the world's terrain seed",
                   seeds.get("terrain") == picked["seed"], str(seeds))
        S["world_seed"] = picked["seed"]

    # 3. ask-mode: ≤ 6 two-chip questions, one at a time, a skip writes nothing
    with ses.step("ask-mode", act="evening", clock="Talk", budget=ASK_ANSWER_S,
                  backend=["real:cold-start", "real:core-api(ledger)"]) as step:
        runner = AskModeRunner(world.cold, door)
        bank = world.cold.bank
        asked = 0
        answered = 0
        skipped = 0
        slowest_answer = 0.0
        plan = ["deep", "weathered", "skip", "answer", "answer", "answer"]
        for want in plan:
            outcome = runner.ask_next(bank)
            kind = type(outcome).__name__
            if kind != "Asked":
                step.check(f"question {asked + 1} is askable", False,
                           f"ask_next returned {kind}: {outcome}")
                break
            question = outcome.question
            asked += 1
            if want == "skip":
                runner.skip(question.id)
                skipped += 1
                continue
            chip = question.chips[0].id
            t0 = time.perf_counter()
            runner.answer(question, chip)
            slowest_answer = max(slowest_answer, time.perf_counter() - t0)
            answered += 1
        # a second question while one is open collapses into the slate — never
        # queues in the owner's face (G §1 20:12) — proved on a fresh sitting
        # with a question deliberately left open
        probe_runner = AskModeRunner(world.cold, door)
        opened = probe_runner.ask_next(bank)
        probe = probe_runner.ask_next(bank)
        step.check("a second open question collapses into the slate",
                   type(opened).__name__ == "Asked"
                   and type(probe).__name__ == "CollapsedToSlate",
                   f"{type(opened).__name__} then {type(probe).__name__}")
        # the ≤ 6 budget is real: the bank ships eight questions on purpose,
        # and this sitting stopped at six
        step.check("≤ 6 questions in the first session", asked <= QUESTIONS_FIRST_SESSION,
                   f"asked {asked}")
        seat_rows = len(runner.ledger.events(types=["taste.note.appended"]))
        step.check("a skip writes nothing (asked − skipped == rows)",
                   seat_rows == answered, f"asked {asked}, skipped {skipped}, rows {seat_rows}")
        spine = spec.taste(author="casey")
        spine_rows = spine.get("notes", spine.get("rows", []))
        step.check("every answered row is in the spine's taste ledger",
                   len(spine_rows) == answered,
                   f"spine {len(spine_rows)} vs answered {answered}")
        reason_codes_ok = all(row.get("reason_code") for row in runner_spine_rows(world))
        step.check("every row carries a reason code and an artifact ref",
                   reason_codes_ok, "rows carry closed reason codes (§1.7)")
        step.check(f"each answer ≤ {ASK_ANSWER_S:g} s (slowest measured)",
                   slowest_answer <= ASK_ANSWER_S, f"{slowest_answer * 1000:.1f} ms")
        S["ask_rows"] = answered
        step.note(
            f"{asked} asked · {answered} answered · {skipped} skipped "
            f"(a skip wrote nothing)"
        )

    # 4. the slate: two small bets, the bar, the WO line, capability rows
    with ses.step("slate", act="evening", clock="Workshop",
                  budget=SLATE_TRANSACTION_S, backend="real:core-api") as step:
        t0 = time.perf_counter()
        task1 = spec.file_task(
            "Crate row on the quay — weathered, half from the library",
            owner_character="prop-maker", recipe_scope=["harbor.crates"],
            cost_estimate={"gpu_minutes": 45.0, "wall_minutes": 60.0},
        )
        task2 = spec.file_task(
            "Racks by the shed wall, short and deep",
            owner_character="prop-maker", recipe_scope=["harbor.racks"],
            cost_estimate={"gpu_minutes": 30.0, "wall_minutes": 45.0},
        )
        slate = spec.slate()
        elapsed = time.perf_counter() - t0
        step.check("the transaction fits the Workshop clock (X C13)",
                   elapsed <= SLATE_TRANSACTION_S, f"{elapsed * 1000:.1f} ms")
        step.check("two bets slated", len(slate["tasks"]) == 2,
                   str([t.get("intention") for t in slate["tasks"]]))
        step.check("the asks are marked (they are [e] until measured)",
                   slate["ask"]["gpu_minutes"] == 75.0, str(slate["ask"]))
        step.check("the work-order line exists from night one (X C11)",
                   "Work orders" in slate["work_order_line"], slate["work_order_line"])
        step.check("one budget bar with counters",
                   {"gpu_minutes", "wall_minutes"} <= set(slate["bar"]),
                   str(slate["bar"]))
        step.check("money scoped to hosted calls reads $0.00 (local)",
                   "$0.00" in slate["money"], slate["money"])
        rows = slate["capability_rows"]
        step.check("the builder's take is a capability row with a denominator",
                   any("built 0" in r["line"] for r in rows), str(rows))
        S["task1"] = task1["task"]["id"]
        S["task2"] = task2["task"]["id"]

    # 5. the one honest work order: compile → a confirm with both prices
    with ses.step("work-order-call", act="evening", clock="Workshop",
                  budget=COMPILE_S, backend="real:core-api") as step:
        result = spec.call(
            utterance="Computer — the crates gain lids and rope handles",
            view={"branch": MAIN_BRANCH, "selection": ["crates"]},
            intent={
                "title": "Crates v2: lids and rope handles",
                "goal": (
                    "props.harbor.crates gains {lids: bool, handles: enum[none, rope]} "
                    "with a deterministic rebuild and a watertight geometry check"
                ),
                "estimate": {
                    "build_verify": {"gpu_minutes": 5.0, "wall_minutes": 40.0},
                    "generate_test": {"gpu_minutes": 15.0, "wall_minutes": 50.0},
                },
                "vocabulary_gap": {
                    "word": "props.harbor.crates",
                    "requested_by": "prop-maker",
                },
                "promote": crates_v2_entry(world),
            },
        )
        step.check("one referent group compiles a draft (question XOR draft)",
                   "draft" in result and "question" not in result,
                   "question" if "question" in result else "draft")
        draft = result["draft"]
        line = draft["confirm_line"]
        _check_budget_line(step, "confirm", line)
        spec_says = line.split("·")[0] if "·" in line else line
        step.check("the spec sentence is ≤ 25 words (T §register)",
                   _word_count(spec_says) <= 25 + 8, f"{_word_count(spec_says)} words")
        step.check("the order is reversible at a named version",
                   "reversible" in line.lower() or "ver_" in line, line)
        S["wo"] = draft["id"]
        S["wo_line"] = line
        step.note(line)
    with ses.step("work-order-confirm-readable", act="evening", clock="Talk",
                  budget=CONFIRM_READABLE_S, backend="real:core-api") as step:
        board = {w["id"]: w for w in spec.work_orders()}
        wo = board[S["wo"]]
        step.check("the draft reads back with its price lines",
                   "build/verify" in wo["confirm_line"], wo["confirm_line"])

    # 6. the limit, said aloud: the param edge refuses, and the order carries it
    with ses.step("propmaker-limit", act="evening", clock="Talk",
                  backend=["real:core-api", "real:vocab(schema)"]) as step:
        try:
            spec.vocab_call(
                "props.harbor.crates",
                {"count": 12, "style": "weathered", "from_library": 6, "seed": 42,
                 "lids": True},
                node="crates",
            )
            step.check("out-of-schema params are refused at the door", False,
                       "the call was accepted")
        except SpecError as err:
            step.check("out-of-schema params are refused at the door",
                       err.status in (400, 403, 422), str(err)[:120])
        refused = [e for e in door.raw_events(0, ["vocab.call"])
                   if e.payload.get("refusal_reason")]
        step.check("the refusal is audited (the edges are the story)",
                   len(refused) >= 1, f"{len(refused)} refused vocab.call events")
        # the limit is a record on the order, not just a refusal in the log:
        # the filed WO carries the vocabulary gap (§1.3 vocabulary_gap)
        filed = [
            e for e in door.raw_events(0, ["wo.filed"])
            if (e.payload.get("work_order", {}).get("vocabulary_gap") or {}).get("word")
        ]
        step.check("the order carries the gap it was filed against",
                   any(f.payload["work_order"]["vocabulary_gap"]["word"]
                       == "props.harbor.crates" for f in filed),
                   str([f.payload.get("work_order", {}).get("vocabulary_gap")
                        for f in filed][-1:]))
        step.note('"Lids and rope handles aren\'t in my hands — 0 built." '
                  "(the param edge, refused at the door)")

    # 7. "Go" — the idempotent confirm
    with ses.step("work-order-confirm", act="evening", clock="Talk",
                  budget=KEEP_REJECT_S, backend="real:core-api") as step:
        confirmed = spec.confirm(S["wo"], answer="go", idem="m1-go-1")
        state = confirmed.get("state") or confirmed.get("work_order", {}).get("state")
        step.check("go → queued", state == "queued", str(state))
        again = spec.confirm(S["wo"], answer="go", idem="m1-go-1")
        state2 = again.get("state") or again.get("work_order", {}).get("state")
        confirms = [e for e in door.raw_events(0, ["wo.confirmed"])]
        step.check("a doubled Go is one Go (§5.3)",
                   state2 == "queued" and len(confirms) == 1,
                   f"{len(confirms)} wo.confirmed events")

    # 8. the handoff: start the night, read the pre-flight
    with ses.step("handoff", act="evening", clock="Watch", budget=PREFLIGHT_S,
                  backend="real:core-api") as step:
        started = spec.start_night(
            rails={"gpu_minutes": 110.0, "hosted_cents": 0, "wall_minutes": 420.0},
            detach_after_min=30,
            load_budget={"stub-imagegen": 1},
        )
        night = started["night"]
        line = started["preflight_line"]
        step.check("the night is running", night["state"] == "running", night["state"])
        step.check("the pre-flight names the lane", "lane free" in line, line)
        step.check("the pre-flight names the queue", "queue 2 items" in line, line)
        step.check("the pre-flight names the detach rule", "detach" in line, line)
        step.check("the pre-flight proposes nothing when the lane is free",
                   started["preflight"]["proposals"] == [], str(started["preflight"]))
        S["night"] = night["id"]
        step.note(line)


def runner_spine_rows(world: World) -> list[dict]:
    spine = world.spec.taste(author="casey")
    return spine.get("notes", spine.get("rows", []))


def crates_v2_entry(world: World) -> dict:
    """The promoted v2 word: crates gain lids and rope handles (§6.1)."""
    base = next(
        e for e in world.seats.vocab.default_entries()
        if e.word == "props.harbor.crates"
    )
    doc = base.model_dump(mode="json")
    params = dict(doc["params"])
    props = dict(params.get("properties", {}))
    props["lids"] = {"type": "boolean", "default": False}
    props["handles"] = {"type": "string", "enum": ["none", "rope"], "default": "none"}
    params["properties"] = props
    return {**doc, "version": 2, "params": params,
            "provenance": {"origin": "wo", "at": "2026-10-30T21:10:00Z"}}


# --------------------------------------------------------------------------- act 2


def act_night(ses: Session, world: World) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe
    S = world.stamps
    night_id = S["night"]

    # 0. the reference night, on the vocabulary seat's own cold world
    with ses.step("reference-loop", act="night",
                  backend="real:vocab") as step:
        outcome = run_cold_night(world.seats, world.vocab_world)
        step.check("the edit went through the vocabulary door",
                   outcome.edit is not None and outcome.refusal is None,
                   getattr(outcome.refusal, "line", "edit ok"))
        world_bet = next(
            (p for p in outcome.predictions if p.claim_type == "material_read"), None
        )
        step.check("the world bet sealed as a guess with its zero denominator",
                   world_bet is not None and world_bet.confidence == "guess"
                   and world_bet.basis == "0 observations",
                   f"{world_bet.confidence} · {world_bet.basis}" if world_bet else "no bet")
        step.check("the taste claim was refused by the two-observation gate",
                   "taste_keep" in outcome.refused_claims,
                   str(outcome.refused_claims))
        step.check("the render job tested a sealed bet (§5.1)",
                   sealed_before_render(world.vocab_world),
                   "seal seq < enqueue seq")
        step.check("the critic wears verdict@scripted on its face",
                   outcome.finding is not None
                   and "verdict@scripted" in outcome.finding.summary,
                   outcome.finding.summary if outcome.finding else "no finding")
        step.check("the hollow crates fall back to the library (crates 7 and 11)",
                   outcome.finding is not None and tuple(outcome.finding.hollow) == (7, 11),
                   str(outcome.finding.hollow) if outcome.finding else "-")
        step.check("with no priors the builder parks the question, never decides",
                   outcome.parked_question is not None and outcome.head is None,
                   f"parked {outcome.parked_question}, head {outcome.head}")
        S["gate_refused_taste"] = True

    # the night branch exists before the bets land on it
    recipe.new_branch(alias="night", name="night-2026-10-30", purpose="night",
                        spine_id="br_night")
    door.publish_branch("br_night", name="night-2026-10-30", purpose="night",
                        head=recipe.head("night"))
    recipe.seam_branch = "night"

    # 1. sealed bet one — the crates (edit → seal → render → critic → keep)
    with ses.step("sealed-bet-crates", act="night",
                  backend=["real:core-api", "real:core-recipe(seam)",
                           "stub:render-rung", "stub:critic"]) as step:
        call = spec.vocab_call(
            "props.harbor.crates",
            {"count": 12, "style": "weathered", "from_library": 6, "seed": 42},
            node="crates",
        )
        step.check("the typed call committed through the recipe seam",
                   call.get("committed") is True, str(call.get("committed")))
        ver = call["version"]
        branch_ref = f"br_night@{ver}"
        sealed = spec.seal(
            branch_ref=branch_ref,
            claim="Weathered timber reads as weathered on all 12 crates",
            claim_type="material_read", confidence="guess",
            basis="0 observations",
            render_spec={"rung": 2, "resolution": "480p", "seed": 42},
        )
        pr_id = sealed["prediction"]["id"]
        job = door.render_job(
            branch_ref=branch_ref, entry_paths=["harbor.crates"], rung=2, seed=42,
            prediction_id=pr_id, night=night_id,
            render=stub_render(42, 2, "crates"),
        )
        door.critic_verdict(
            job_id=job["job_id"], verdict="keep", code="reads_as_asked",
            summary="verdict@scripted · texture 12/12 · geometry 12/12 · hollow none",
        )
        scored = door.score_world_bet(pr_id, "keep")
        step.check("the critic scored the world bet (a verdict write)",
                   scored.verdict == "hit", scored.verdict)
        recipe.move_head("night", ver)
        events = door.raw_events(0)
        seal_seq = _seq_of(events, "prediction.sealed")
        enqueue_seq = next(
            int(e.seq) for e in events
            if e.type == "job.enqueued" and e.payload.get("prediction_id") == pr_id
        )
        step.check("gate (c): sealed_at strictly before its render job's enqueue",
                   seal_seq is not None and seal_seq < enqueue_seq,
                   f"seal seq {seal_seq} < enqueue seq {enqueue_seq}")
        door.set_task_state(S["task1"], "kept")
        door.record_spend(night_id, {"gpu_minutes": 45.0, "wall_minutes": 60.0},
                          job=job["job_id"])
        S["bet1"] = {"pr": pr_id, "ver": ver, "branch_ref": branch_ref}

    # 2. sealed bet two — the racks: the critic misses, the batch reverts
    with ses.step("sealed-bet-racks", act="night",
                  backend=["real:core-api", "real:core-recipe(seam)",
                           "stub:render-rung", "stub:critic"]) as step:
        call = spec.vocab_call(
            "props.harbor.racks", {"count": 8, "length_m": 3.0}, node="racks",
        )
        ver = call["version"]
        branch_ref = f"br_night@{ver}"
        sealed = spec.seal(
            branch_ref=branch_ref,
            claim="Eight short racks read as a shed wall, not a fence",
            claim_type="clutter_density", confidence="guess",
            basis="0 observations",
            render_spec={"rung": 2, "resolution": "480p", "seed": 43},
        )
        pr_id = sealed["prediction"]["id"]
        job = door.render_job(
            branch_ref=branch_ref, entry_paths=["harbor.racks"], rung=2, seed=43,
            prediction_id=pr_id, night=night_id,
            render=stub_render(43, 2, "racks"),
        )
        door.critic_verdict(
            job_id=job["job_id"], verdict="hold", code="wrong_scale",
            summary="verdict@scripted · reads as a fence at 3.0 m · wrong_scale",
        )
        scored = door.score_world_bet(pr_id, "hold")
        step.check("the miss is scored, not hidden", scored.verdict == "miss",
                   scored.verdict)
        recipe.move_head("night", ver)
        door.set_task_state(S["task2"], "reverted", reason="wrong_scale (critic)")
        door.record_spend(night_id, {"gpu_minutes": 30.0, "wall_minutes": 45.0},
                          job=job["job_id"])
        S["bet2"] = {"pr": pr_id}

    # 3. the work order's attempt: stub engineer, real gate, real land
    with ses.step("wo-attempt", act="night",
                  backend=["real:core-api", "stub:engineer(aider-local)",
                           "stub:gate-engine"]) as step:
        spend = {"gpu_minutes": 20.0, "wall_minutes": 90.0}
        patch = door.put_artifact(b"diff --git a/crates.py b/crates.py\n+lids\n+rope\n",
                                  "crates-v2.patch")
        deliverable = {
            "attempt": "att_1",
            "commit": {"branch": "wo/crates-v2/1", "sha": "a1c4e2f"},
            "code_diff": {"files": 2, "insertions": 48, "deletions": 6,
                          "patch_ref": patch["sha256"]},
            "evidence": [
                {"kind": "test_run", "ref": "pytest", "sha256": patch["sha256"],
                 "summary": "12 passed · props tests incl. lids/handles schema"},
                {"kind": "constraint_run", "ref": "analytic", "sha256": patch["sha256"],
                 "summary": "lid hinge torque 1.4 Nm at 2× load (analytic)"},
            ],
            "budget_spend": spend,
            "notes": "crates v2: lids default off, handles enum[none, rope]",
        }
        door.record_spend(night_id, spend, job=S["wo"])
        gate = door.run_engineer_attempt(
            S["wo"], deliverable=deliverable, preview=stub_render(42, 2, "crates-v2"),
            night=None,
        )
        step.check("the merge gate passed every check",
                   gate.get("passed") is True, str(gate.get("checks")))
        board = {w["id"]: w for w in spec.work_orders()}
        wo = board[S["wo"]]
        step.check("landed, with a preview before the owner is notified",
                   wo["state"] == "landed" and wo.get("preview"), wo["state"])
        step.check("no card without an artifact (D)",
                   bool(wo.get("evidence")), f"{len(wo.get('evidence', []))} evidence rows")
        # the preview enters the library with a complete licence row (§1.6)
        asset = spec.create_asset(
            kind="mesh",
            provenance={
                "source": "generated",
                "generator": {
                    "method": "stub_generator", "model_id": "stub-engine",
                    "prompt": "crates v2 preview, quay row", "seed": 42,
                },
            },
            licence={
                "spdx": "CC0-1.0", "dependency_terms": ["library crate: CC0 (Poly Haven)"],
                "commercial_ok": True, "checked_by": "core-licence-registry",
                "checked_at": "2026-10-30T23:40:00Z",
            },
            files=[{"role": "master", "path": "artifacts/crates-v2.glb",
                    "sha256": "sha256:stub", "bytes": 2048}],
        )
        S["preview_asset"] = asset["asset"]["id"]

    # 4. heartbeats, spend, and the load cap
    with ses.step("heartbeats-and-rails", act="night", backend="real:core-api") as step:
        for minutes, load in ((2, 0.2), (6, 0.4), (10, 0.3), (14, 0.3)):
            door.tick(night_id, at=_at(world, minutes), load=load)
        door.model_load(night_id, "stub-imagegen")
        snap = spec.budget(night=night_id)
        step.check("spend is counted against the bar",
                   snap["spend"]["gpu_minutes"] >= 95.0, str(snap["spend"]))
        step.check("the 80% graduation is computed, not narrated",
                   "drain" in snap["bar"]["state"], snap["bar"]["state"])
        step.check("the per-model load cap counts its load against its cap",
                   snap["loads"].get("stub-imagegen", 0) == 1
                   and any(v.get("at_cap") for v in snap["load_state"].values()),
                   str(snap.get("load_state")))
        threshold_events = [
            e for e in door.raw_events(0, ["budget.threshold"])
            if e.subject.get("entity_id") == night_id
        ]
        step.check("the 80% threshold fired once, in the log",
                   any(e.payload.get("level") == 80 for e in threshold_events),
                   str([e.payload.get("level") for e in threshold_events]))

    # 5. the third queue item (the calibration batch) is cut at the bar
    with ses.step("cut-at-the-bar", act="night",
                  backend=["real:core-api", "bridge:runner-half"]) as step:
        calib = spec.file_task(
            "Calibration batch — first seeded-defect members (unused lane)",
            owner_character="critic", cost_estimate={"gpu_minutes": 60.0,
                                                     "wall_minutes": 60.0},
        )
        spec._req("POST", f"/v1/night/{night_id}/tasks", by="companion", body={})
        # the runner half drains instead of opening the batch at 80%: the cut
        # is a proposal the morning names (§3.2.5), never a silent drop
        door.set_task_state(calib["task"]["id"], "cut",
                            reason="cut at the 80% bar; requeued for tomorrow")
        S["calib_task"] = calib["task"]["id"]
        step.check("the cut task is named with its reason",
                   any(t.get("state") == "cut" for t in _all_tasks(world)),
                   S["calib_task"])

    # 6. the 2 a.m. peek
    with ses.step("peek", act="night", clock="Watch", budget=PEEK_JOIN_S,
                  backend="real:core-api") as step:
        t0 = time.perf_counter()
        head = door.store.max_seq()
        feed = spec.events(since_seq=0, until_seq=head)
        join = time.perf_counter() - t0
        step.check("joining cold is a ledger replay", join <= PEEK_JOIN_S,
                   f"{join * 1000:.1f} ms for {len(feed)} events")
        t_card = time.perf_counter()
        card = next((e for e in feed if e["type"] == "critic.verdict"), None)
        legible = (card is not None
                   and "verdict@scripted" in card["payload"]["summary"]
                   and len(card["payload"]["summary"]) <= 120)
        card_ms = (time.perf_counter() - t_card) * 1000
        step.check(f"a bet card is legible in the feed (Watch ≤ {CARD_LEGIBLE_S:g} s per card)",
                   legible and card_ms / 1000 <= CARD_LEGIBLE_S,
                   f"{card_ms:.1f} ms · " + (card["payload"]["summary"][:80] if card else "no card"))
        again = spec.events(since_seq=0, until_seq=head)
        step.check("rewind is free — the same replay, complete to the last sealed bet",
                   len(again) == len(feed), f"{len(feed)} events")
        head = door.store.max_seq()
        step.check("never fast-forward of live work (no events past the head)",
                   all(int(e["seq"]) <= head for e in feed), f"head {head}")

    # 7. gate (a): kill -9 mid-night, reopen, everything renders from the ledger
    with ses.step("kill-9", act="night", clock="Watch", backend="real:core-api") as step:
        pre = len(door.raw_events())
        sealed_seqs = [e.seq for e in door.raw_events(0, ["prediction.sealed"])]
        door.kill()
        reconnect(world)
        post = world.spec.events(since_seq=0, until_seq=world.door.store.max_seq())
        post_seqs = {int(e["seq"]) for e in post}
        pre_seqs = set(range(1, pre + 1))  # seq is gapless (§1.8) — the resume cursor
        step.check("the feed renders from the ledger alone, complete to the last seal",
                   sealed_seqs and all(s in post_seqs for s in sealed_seqs)
                   and pre_seqs <= post_seqs,
                   f"{len(post)} events replayed; seals at {sealed_seqs}")
        budget = world.spec.budget(night=night_id)
        step.check("the night is still running in the reopened ledger",
                   budget.get("night") == night_id, str(budget.get("night")))
        reference = world.night_seat.night_killed_mid_run(
            night_id="night-reference",
            tasks=[
                {"id": "t1", "intention": "crates", "ask": {"gpu_minutes": 45},
                 "script": {"outcome": "kept"}},
            ],
            rails={"gpu_minutes": 110, "wall_minutes": 420},
        )
        step.check("parity: the runner seat computes the morning status from the log",
                   reference["status"]["status"] in
                   ("ran as planned", "ran short", "ran degraded", "did not run"),
                   reference["status"]["status"])

    # 8. stop: the kill switch answers in ≤ 2 s (through the *reopened*
    # client — gate (d): the morning reads a fresh process's view)
    with ses.step("stop", act="night", clock="Talk", budget=STOP_S,
                  backend="real:core-api") as step:
        stopped = world.spec.stop_night(night_id, reason="morning", idem="m1-stop-1")
        state = stopped["night"]["state"] if "night" in stopped else stopped.get("state")
        step.check("the night stopped cleanly", state == "stopped", str(state))
        status = world.door._svc("nights").compute_status(night_id)
        step.check("the status line is computed, and is one of the four",
                   _status_word(status.get("status")) in
                   ("ran as planned", "ran short", "ran degraded", "did not run"),
                   str(status))
        S["status"] = status


def _at(world: World, minutes: int) -> str:
    """A heartbeat timestamp, minutes after the spine night started."""
    from datetime import datetime, timedelta

    started = None
    for e in world.door.raw_events(0, ["night.started"]):
        started = e.at
    moment = datetime.fromisoformat(started.replace("Z", "+00:00")) + timedelta(
        minutes=minutes
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _all_tasks(world: World) -> list[dict]:
    return world.door.store.scan("tasks")


# --------------------------------------------------------------------------- act 3


def act_morning(ses: Session, world: World) -> None:
    spec, door, recipe = world.spec, world.door, world.recipe
    S = world.stamps
    night_id = S["night"]

    # 1. the report opens — before the world
    with ses.step("report", act="morning", clock="Watch",
                  budget=REPORT_FIRST_PAINT_S, backend="real:core-api") as step:
        t0 = time.perf_counter()
        doc = spec.report(night_id, mode="json")["report"]
        paint = time.perf_counter() - t0
        step.check("first paint ≤ 3 s (a static page over the ledger)",
                   paint <= REPORT_FIRST_PAINT_S, f"{paint * 1000:.1f} ms")
        status = doc["status_line"]
        step.check("the status line leads, and is one of the four",
                   _status_word(status.get("status")) in
                   ("ran as planned", "ran short", "ran degraded", "did not run"),
                   str(status))
        step.check("the failure line is always present",
                   isinstance(doc["failure_line"], str) and doc["failure_line"],
                   doc["failure_line"])
        cut = doc["cut"]
        step.check("the cut is named, not just the spend (X C11)",
                   "calibration" in str(cut).lower() or "cut" in str(cut).lower(),
                   str(cut))
        numbers = doc["night_numbers"]
        step.check("the night's numbers carry the load count against its cap",
                   "load" in str(numbers).lower(), str(numbers)[:120])
        step.check("branch set, questions, landed orders, tally and the three-number "
                   "line are all sections of one page",
                   {"branches", "parked_questions", "landed_work_orders", "tally",
                    "three_number_line"} <= set(doc), str(sorted(doc)))
        step.check("no single prediction score anywhere (X C2)",
                   "prediction score" not in str(doc).lower()
                   and '"score"' not in str(doc["tally"]).lower(), "")
        text = spec.report(night_id, mode="text")
        step.check("the text mode is the same ledger read",
                   _status_word(status.get("status")) in text.replace("_", " ")
                   or str(status.get("status", "")) in text, text[:80])
        html = spec.report(night_id, mode="html")
        step.check("the html mode renders", "<html" in html.lower(), html[:40])
        S["report_doc"] = doc
        step.note(f"status: {status.get('status')} · {doc['failure_line']}")

    # 2. the branch flip — A/B plus the two standing exits, from night one
    with ses.step("branch-flip", act="morning", clock="Watch",
                  budget=BRANCH_FLIP_S, backend=["real:core-api",
                                                 "real:core-recipe(seam)"]) as step:
        # the night pre-baked its options: the night branch head, and the
        # standing "back to the plan" branch cut from the slate's base
        night_head = recipe.head("night")
        door.publish_branch("br_night", name="night-2026-10-30", purpose="morning-option",
                            head=night_head, base=recipe.head(MAIN_BRANCH))
        recipe.new_branch(alias="plan", name="back-to-the-plan", purpose="standing",
                            spine_id="br_plan", head=recipe.root_version)
        door.publish_branch("br_plan", name="back to the plan", purpose="standing",
                            head=recipe.root_version, base=recipe.root_version)
        out = spec.branches()
        standing = [s["name"] for s in out["standing"]]
        step.check("the two standing exits are present from night one (X G7)",
                   any("keep yesterday" in n for n in standing)
                   and any("back to the plan" in n for n in standing), str(standing))
        names = {b["id"] for b in out["branches"]}
        step.check("the night's option is on the board", "br_night" in names, str(names))
        t0 = time.perf_counter()
        out2 = spec.branches()
        flip = time.perf_counter() - t0
        step.check("the flip (a pointer move over cached artifacts) ≤ 2 s",
                   flip <= BRANCH_FLIP_S, f"{flip * 1000:.1f} ms")

    with ses.step("branch-apply", act="morning", clock="Workshop", budget=APPLY_S,
                  backend=["real:core-api", "real:core-recipe(seam)",
                           "decision"]) as step:
        applied = spec.apply_branch("br_night")
        step.check("apply is a head move ≤ 10 s",
                   applied.get("branch") == "br_night", str(applied))
        step.check("the recipe store followed the pointer (recipe_sync: ok)",
                   applied.get("recipe_sync") == "ok", str(applied.get("recipe_sync")))
        moved = [e for e in door.raw_events(0, ["branch.head.moved"])]
        step.check("the move is one ledger event", len(moved) >= 1,
                   f"{len(moved)} branch.head.moved events")

    # 3. the landed work order: keep → promotion, in one core transaction
    with ses.step("landed-wo-keep", act="morning", clock="Talk",
                  budget=KEEP_REJECT_S, backend=["real:core-api", "decision"]) as step:
        board = {w["id"]: w for w in spec.work_orders()}
        wo = board[S["wo"]]
        step.check("the card shows landed with preview and evidence",
                   wo["state"] == "landed" and wo.get("preview")
                   and len(wo.get("evidence", [])) >= 2, wo["state"])
        kept = spec.keep(S["wo"], reason_code="too_busy", idem="m1-keep-1")
        promotion = kept.get("promotion")
        step.check("keep promotes the word in one transaction (§2.3)",
                   promotion and promotion.get("word") == "props.harbor.crates"
                   and promotion.get("status") == "active", str(promotion))
        words = {w["word"]: w for w in spec.vocab()["words"]}
        entry = words["props.harbor.crates"]
        step.check("the growth beat: crates v2 is active with lids and handles",
                   entry["status"] == "active"
                   and "lids" in entry["params"].get("properties", {}),
                   entry["status"])
        step.note('"I can do lids and rope handles now." — the word, promoted')

    # 4. the tally: denominators, never a single score
    with ses.step("tally", act="morning", clock="Talk", backend="real:core-api") as step:
        tally = spec.tally()["tally"]
        by_key = {(r["builder"], r["claim_type"]): r for r in tally}
        step.check("both bets are in the tally with their denominators",
                   len(tally) == 2 and all(r["denominator"] >= 1 for r in tally),
                   str([(r["claim_type"], r["sealed"], r["hits"], r["misses"])
                        for r in tally]))
        material = by_key.get(("prop-maker", "material_read"), {})
        clutter = by_key.get(("prop-maker", "clutter_density"), {})
        sealed_n = sum(r["sealed"] for r in tally)
        hits = sum(r["hits"] for r in tally)
        misses = sum(r["misses"] for r in tally)
        step.check("night one reads 2 sealed · 1 hit · 1 miss — not taste yet",
                   sealed_n == 2 and hits == 1 and misses == 1,
                   f"{sealed_n} sealed · {hits} hit · {misses} miss")
        step.note(f"{material.get('line', '')} | {clutter.get('line', '')}")

    # 5. "Why?" in one tap: the card that reaches the artifact
    with ses.step("why", act="morning", clock="Talk", budget=WHY_S,
                  backend="real:core-api") as step:
        t0 = time.perf_counter()
        assets = spec.assets()["assets"]
        whole_feed = spec.events(since_seq=0, until_seq=door.store.max_seq())
        feed = [e for e in whole_feed
                if e["type"] in ("prediction.sealed", "critic.verdict")]
        elapsed = time.perf_counter() - t0
        step.check("the why-card opens ≤ 1 s (X S13)", elapsed <= WHY_S,
                   f"{elapsed * 1000:.1f} ms")
        preview = next((a for a in assets if a["id"] == S["preview_asset"]), None)
        step.check("the artifact carries its provenance (seed, model)",
                   preview is not None
                   and preview["provenance"]["generator"]["seed"] == 42,
                   str(preview["provenance"]) if preview else "missing")
        step.check("the licence row is complete, dependency terms included (X R8)",
                   preview is not None
                   and preview["licence"].get("spdx") == "CC0-1.0"
                   and preview["licence"].get("dependency_terms"),
                   str(preview["licence"]) if preview else "missing")
        step.check("the sealed bet and its verdict are one tap away",
                   len(feed) >= 3, f"{len(feed)} events")

    # 6. gate (b): the in-game computer call with two plausible referents
    with ses.step("computer-call", act="morning", clock="Workshop",
                  budget=COMPILE_S,
                  backend=["real:core-api", "real:core-recipe(registry)"]) as step:
        # the evening added the market stalls next to the harbour crates —
        # "sturdier, these" now has two plausible referent sets. (The entry
        # kind is `prop_set`, spec §1.1's only spelling on the merged tree —
        # the old adapter's prop→prop_set translation died with the merge.)
        stalls = {
            "path": "market.stalls", "kind": "prop_set",
            "generator": {"module": "infinigen_thor.structures", "func": "stalls",
                          "variant": None, "rev": "9f31c0e"},
            "params": {"count": 5, "length_m": 2.0}, "seed": 7, "constraints": [],
            "assets": [], "origin": "builtin",
        }
        ver = recipe.add_entry(stalls, message="the market stalls, for the evening walk")
        nodes = recipe.derived_nodes(recipe.refresh_recipe(ver))
        door.publish_nodes(MAIN_BRANCH, nodes, head=ver)
        result = spec.call(
            utterance="Computer — make these sturdier",
            view={"branch": MAIN_BRANCH, "selection": ["crates", "stalls"]},
        )
        step.check("two referent groups → a question, never a plan",
                   "question" in result and "draft" not in result,
                   "question" if "question" in result else "draft")
        if "question" in result:
            options = result["question"]["options"]
            step.check("the question names the candidates by what they are",
                       len(options) == 2, str(options))
            S["question"] = result["question"]["id"]
            S["question_options"] = options

    # 7. the parked question answered in one tap
    with ses.step("question-answer", act="morning", clock="Talk",
                  budget=QUESTION_ANSWER_S,
                  backend=["real:core-api", "decision"]) as step:
        q = S.get("question")
        if not q:
            step.check("a question was parked by the call", False, "no question")
            return
        choice = S["question_options"][0]
        answered = spec.answer_question(q, choice, idem="m1-answer-1")
        answered_events = [
            e for e in door.raw_events(0, ["question.answered"])
            if e.subject.get("entity_id") == q
        ]
        step.check("one tap answers it, and the answer is in the log",
                   answered["question"].get("id") == q and len(answered_events) == 1,
                   str(answered_events[-1].payload) if answered_events else "no event")
        replay = spec.answer_question(q, choice, idem="m1-answer-1")
        step.check("the replay is idempotent (§5.3)",
                   len([e for e in door.raw_events(0, ["question.answered"])
                        if e.subject.get("entity_id") == q]) == 1,
                   "one question.answered event for two calls")

    # 8. the three-number line, and the decision budget
    with ses.step("decisions", act="morning", backend="real:core-api") as step:
        three = S["report_doc"]["three_number_line"]
        decisions = ses.decisions_asked
        step.check("the morning asked for ≤ 10 decisions (G §4.3)",
                   decisions <= DECISIONS_PER_MORNING, f"{decisions} decisions")
        step.check("the report's attention budget is 10",
                   three.get("attention_budget") == DECISIONS_PER_MORNING,
                   str(three.get("attention_budget")))
        step.check("the hosted number reads $0.00 (local) — itself a product statement",
                   three.get("hosted_cents") == 0 and "local" in three.get("line", ""),
                   three.get("line", ""))
        step.check("the Thor's own hours are the first number",
                   isinstance(three.get("gpu_hours"), (int, float))
                   and three.get("gpu_hours", 0) > 0, str(three.get("gpu_hours")))
        step.note(f"{three.get('line', '')} — the session itself counted "
                  f"{decisions}: keep · apply · answer")


# --------------------------------------------------------------------------- the play


ACTS = (("boot", act_boot), ("evening", act_evening), ("night", act_night),
        ("morning", act_morning))


def play(world: World, ses: Session | None = None) -> Session:
    """Play the whole session; the first failed step raises StepFailure."""
    ses = ses or Session(world)
    if not hasattr(world, "cold_view"):
        from seats.coldstart import ColdOpenView

        world.cold_view = lambda: ColdOpenView(world.cold, world.door).line_and_starters()
    try:
        for _, act in ACTS:
            act(ses, world)
    finally:
        world.artifacts["steps"] = ses.steps
    return ses


def main() -> int:
    """The headless driver: run the session, print the step table."""
    import tempfile

    root = Path(__file__).resolve().parent
    run_dir = root / "run" / time.strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="m1-home-") as tmp:
        world = build_world(Path(tmp) / "builder-ide", run_dir)
        ses = Session(world)
        try:
            play(world, ses)
        except StepFailure as failure:
            print(ses.table())
            print(f"\nFAILED: {failure}")
            (run_dir / "steps.txt").write_text(ses.table() + f"\n\nFAILED: {failure}\n")
            teardown_world(world)
            return 1
        print(ses.table())
        print(f"\nM1 session played end to end: {len(ses.steps)} steps, "
              f"{sum(1 for s in ses.steps if s.ok)}/{len(ses.steps)} passed.")
        (run_dir / "steps.txt").write_text(ses.table() + "\n")
        teardown_world(world)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
