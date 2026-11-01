"""The night driver's ledger payloads must be canonical-JSON-clean.

Run B died in its preflight ledger row — ``TypeError: Object of type
CutLine is not JSON serializable`` — after three and a half hours of
waiting for the heavy lock: the payload carried the admission check's
``cut`` and ``parked`` lists raw, and ``canonical_bytes`` (the ledger's
own gate at append) refuses anything canonical JSON cannot write. The fix
dumps the models before the ledger or the morning sees them, in one
shared builder (``run_night.admission_rows``) that both payload sites —
the preflight row and the morning — call.

These tests hold that line the way the brief asks: every payload the
driver builds goes through ``canonical_bytes`` with a real ``CutLine`` in
it — once through the driver's own dry run with a cut forced (the real
appends, the real rows, the real morning), once against the builder
directly.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

from core.canon import canonical_bytes
from core.night.cost.admission import CutLine, PlannedJob, admission_check
from core.night.models import Rail

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "docs" / "lab" / "night-v3-scripts" / "run_night.py"


def _import_run_night():
    """The driver, by path: it lives under docs/lab, so no package import."""
    spec = importlib.util.spec_from_file_location("night_v3_run_night", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cut_and_parked_check():
    """A plan that parks one job (its model's load cap is zero) and cuts
    another (the rail is spent) — real ``CutLine`` instances in both
    lists, the run B shape."""
    jobs = [
        PlannedJob(id="world.base", intention="the baseline",
                   ask=Rail(gpu_minutes=1.0, wall_minutes=4.0), kind="rung.2"),
        PlannedJob(id="img:crate", intention="the crate's concepts",
                   ask=Rail(gpu_minutes=2.0, wall_minutes=6.0),
                   model="sd_xl_base_1.0"),
        PlannedJob(id="world.edit", intention="the edit rounds",
                   ask=Rail(gpu_minutes=1.5, wall_minutes=5.0), kind="rung.2"),
    ]
    rails = Rail(gpu_minutes=2.0, wall_minutes=8.0, hosted_cents=100)
    return admission_check(jobs, rails, load_caps={"sd_xl_base_1.0": 0})


def test_admission_rows_dump_the_cut_lines_for_canonical_bytes():
    """The builder's own contract: real CutLines go in, canonical-JSON
    bytes come out — the exact expression that killed run B, held by a
    test now."""
    run_night = _import_run_night()
    check = _cut_and_parked_check()
    assert check.cut and check.parked
    assert all(isinstance(c, CutLine) for c in check.cut)
    assert all(isinstance(c, CutLine) for c in check.parked)
    rows = run_night.admission_rows(check)
    data = canonical_bytes(rows)  # must not raise
    again = json.loads(data.decode("utf-8"))
    assert again["fits"] is False
    assert again["cut"][0]["id"] == "world.edit"
    assert again["cut"][0]["kind"] == "cut"
    assert again["parked"][0]["id"] == "img:crate"
    assert again["parked"][0]["kind"] == "parked"


def test_every_payload_the_dry_run_writes_is_canonical(tmp_path, monkeypatch):
    """The driver's own dry run, with the world's price forced past the
    rails so the admission check really cuts: it must run all the way to
    the morning, and every ledger row it wrote — the preflight and the
    morning's admission half included, the two run B sites — must be
    writable as canonical JSON."""
    run_night = _import_run_night()
    real_price = run_night.price_job

    def cut_price(kind, **kwargs):
        priced = real_price(kind, **kwargs)
        return priced.model_copy(update={
            "ask": Rail(gpu_minutes=1000.0, wall_minutes=1000.0,
                        hosted_cents=1000.0)})

    monkeypatch.setattr(run_night, "price_job", cut_price)
    out = tmp_path / "night-v3-dry"
    assert run_night.main(["--dry-run", "--out", str(out)]) == 0

    db = sqlite3.connect(out / "ledger.db")
    rows = list(db.execute("SELECT type, payload FROM audit"))
    assert rows, "the dry run wrote no ledger rows"
    for _type, payload in rows:
        canonical_bytes(json.loads(payload))  # the ledger's gate, again, by hand

    preflight = json.loads(
        next(p for t, p in rows if t == "night.preflight"))
    assert preflight["admission"]["fits"] is False
    assert preflight["admission"]["cut"], \
        "the forced cut did not reach the preflight row"
    assert all(isinstance(c, dict) for c in preflight["admission"]["cut"])
    assert all(isinstance(c, dict) for c in preflight["admission"]["parked"])

    morning = json.loads((out / "morning.json").read_text())
    assert morning["admission"]["cut"]
    assert morning["admission"]["cut"][0]["id"] == preflight["admission"]["cut"][0]["id"]
    canonical_bytes(morning["admission"])
