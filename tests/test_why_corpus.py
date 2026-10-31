"""Golden corpus pairs — the public equivalence suite.

Each pair under tests/corpus/<name>/ is:
- graph.txt     — the input justification graph
- att.txt       — the root attestations
- expected.txt  — expected statuses, one ``id status`` per line
- note.md       — the surprise note: what this pair pins down and why

The corpus is copied verbatim from the Rust reference implementation
(SuperInstance/why, why-core v0.2) so the Python port is pinned to the same
semantics. A pair that changes behavior is a semantic decision, not a refactor.

``as_of`` dates mirror the Rust test runner so mortality pairs are
deterministic — the kernel itself never reads the wall clock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ecology.why import evaluate, parse_attestation, parse_graph

CORPUS = Path(__file__).parent / "corpus"

# name -> as_of (None = no clock). Mirrors why-core/tests/evaluate.rs.
AS_OF: dict[str, str | None] = {
    "basic_alive": None,
    "basic_dead": None,
    "unknown": None,
    "inferred_live": None,
    "inferred_dead": None,
    "until_expired": "2026-04-01",
    "until_active": "2026-02-01",
    "review_stale": "2026-06-01",
    "review_grace": "2026-01-15",
    "conjunctive": None,
    "coverage_zero": None,
    "mixed_verdicts": None,
    "dead_chain_depth2": None,
    "dead_vs_dangling": None,
    "conjunctive_short_circuit": None,
}

PAIRS = sorted(p.name for p in CORPUS.iterdir() if p.is_dir() and (p / "expected.txt").exists())


def _load_pair(name: str):
    base = CORPUS / name
    graph = parse_graph((base / "graph.txt").read_text())
    att = parse_attestation((base / "att.txt").read_text())
    expected_lines = (base / "expected.txt").read_text().splitlines()
    expected = {}
    for line in expected_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        node_id, status = line.split()
        expected[node_id] = status
    return graph, att, expected


@pytest.mark.parametrize("name", PAIRS)
def test_golden_pair(name: str) -> None:
    graph, att, expected = _load_pair(name)
    evaluation = evaluate(graph, att, AS_OF.get(name))
    failures = [
        f"{node_id}: want {want}, got {evaluation.status_of(node_id).value}"
        for node_id, want in expected.items()
        if evaluation.status_of(node_id).value != want
    ]
    assert not failures, f"golden pair {name}:\n  " + "\n  ".join(failures)


def test_coverage_zero_numbers() -> None:
    """Coverage numbers are part of the golden output — an unwired repository
    must never read as healthy."""
    graph, att, _ = _load_pair("coverage_zero")
    evaluation = evaluate(graph, att, None)
    coverage = evaluation.coverage
    assert coverage is not None, "coverage pair must declare discovered"
    assert coverage.wired == 1
    assert coverage.discovered == 4
    assert abs(coverage.pct - 25.0) < 1e-9


def test_chain_reconstruction() -> None:
    """Derivation chains are part of the contract: no 'trust me' output."""
    graph, att, _ = _load_pair("basic_dead")
    evaluation = evaluate(graph, att, None)
    from ecology.why import chain

    result = chain(graph, evaluation, "role:legacy-export")
    assert result
    assert result[0] == "role:legacy-export"
    assert "project:old-migration" in result
