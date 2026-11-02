"""letter.py — the Biographer's letter to the returning human.

The lineage is night-v4's ``write_letter.py`` (docs/lab/night-v4-scripts):
a letter of at most 150 words, one open question, every number read out of
a ledger and not written in advance. What changed here is the ledger — the
night's own ledger became the world's — and the two rules that pick the
letter's content:

* the **surprise** is the largest thing the ledger measured since the human
  left that the world did not expect: the judge refusing every verdict, if
  it is; otherwise the loudest drift alarm; otherwise the newest skills;
* the **question** is the decision that surprise leaves open — always a
  question the human can actually answer on this screen.

``render(facts)`` takes the ``snapshot()`` dict from :mod:`worldview` and
returns the letter. It writes nothing anywhere.
"""

from __future__ import annotations

from typing import Any

WORD_LIMIT = 150


def _hour_hm(iso: str) -> str:
    return iso[11:16] + "Z" if len(iso) >= 16 else iso


def _pick_surprise(facts: dict[str, Any]) -> dict[str, Any]:
    """The largest measured thing since the human left, by rule."""
    judge = next((l for l in facts["lanes"] if l["role"] == "judge"), {})
    refusal_rate = judge.get("refusal_rate") or 0.0
    if judge.get("verdicts") and refusal_rate >= 0.5:
        return {"kind": "refusal", "lane": judge}
    levels = facts.get("drift", {}).get("levels") or {}
    if sum(levels.values()):
        loudest = "hard" if levels.get("hard") else ("tier" if levels.get("tier") else "soft")
        alarm = next((a for a in reversed(facts["drift"]["alarms"])
                      if a["level"] == loudest), None)
        if alarm:
            return {"kind": "drift", "alarm": alarm}
    if facts["threshold"]["authored"]:
        return {"kind": "skills", "n": facts["threshold"]["authored"]}
    return {"kind": "nothing"}


def _sentence_changed(facts: dict[str, Any]) -> str:
    t = facts["threshold"]
    span = facts["span"]
    hours = "the whole ledger" if not facts["since_epoch"] else \
        f"since {_hour_hm(facts['since'])}"
    bots = sorted((l for l in facts["lanes"] if l["role"] == "character"),
                  key=lambda l: -l.get("plays", 0))
    top = bots[0]["actor"] if bots and bots[0].get("plays") else "no one"
    return (f"While you were away ({hours}; the ledger now holds {span['rows']} rows over "
            f"{span['hours']} h), the world played {t['plays']} skills and took "
            f"{t['verdicts']} verdicts; {top} played the most.")


def _sentence_matters(facts: dict[str, Any], surprise: dict[str, Any]) -> str:
    if surprise["kind"] == "refusal":
        lane = surprise["lane"]
        since_epoch = facts.get("since_epoch") or 0.0
        segs = [s for s in facts.get("refusals", []) if s["end_epoch"] >= since_epoch]
        began = segs[0]["start"] if segs else (lane.get("last_at") or facts["generated_at"])
        running = segs and segs[0].get("still_running")
        tail = ("and is still refusing" if running
                else f"and returned {_hour_hm(segs[0]['end'])}" if segs else "")
        return (f"What matters: the judge refused {lane['refused']} of {lane['verdicts']} "
                f"verdicts ({lane['refusal_rate']:.0%}) — the refusals begin "
                f"{_hour_hm(began)}{', ' + tail if tail else ''}.")
    if surprise["kind"] == "drift":
        a = surprise["alarm"]
        return f"What matters: the loudest drift alarm — {a['reason']}."
    if surprise["kind"] == "skills":
        fams = {a["family"] for a in facts["authored_recent"]}
        return (f"What matters: {surprise['n']} new skills were authored "
                f"({', '.join(sorted(fams)[:3])}).")
    return "What matters: nothing crossed a threshold while you were away."


def _sentence_undone(facts: dict[str, Any]) -> str:
    t = facts["threshold"]
    if t["retired"]:
        return f"The mediator retired {t['retired']} skills as superseded — that work is undone."
    return "Nothing was undone: no skill was retired in the window."


def _sentence_next(facts: dict[str, Any]) -> str:
    return "Next, the world keeps playing; the rewind below is ready if you want it."


def _question(facts: dict[str, Any], surprise: dict[str, Any]) -> str:
    if surprise["kind"] == "refusal":
        lane = surprise["lane"]
        return (f"The judge is refusing {lane['refusal_rate']:.0%} of its verdicts — should "
                "the bots keep choosing skills on their own bandit until it returns, or "
                "pause choosing until it does?")
    if surprise["kind"] == "drift":
        return (f"The drift gate fired ({surprise['alarm']['level']}): rewind to before it "
                f"began, or let the world run through it?")
    return "Nothing is waiting on you — is there anything the letter did not answer?"


def render(facts: dict[str, Any]) -> dict[str, Any]:
    surprise = _pick_surprise(facts)
    parts = [
        _sentence_changed(facts),
        _sentence_matters(facts, surprise),
        _sentence_undone(facts),
        _sentence_next(facts),
    ]
    question = _question(facts, surprise)
    words = sum(len(p.split()) for p in parts) + len(question.split())
    letter = {
        "to": facts["human"],
        "paragraphs": parts,
        "question": question,
        "word_count": words,
        "surprise_kind": surprise["kind"],
        "within_limit": words <= WORD_LIMIT,
        "receipts": [
            "world-ledger.sqlite3 (read-only): tile.played, judge.verdict, "
            "tile.authored, tile.retired",
            "core.drift over the same ledger (rate gates, 5-minute windows)",
        ],
    }
    return letter
