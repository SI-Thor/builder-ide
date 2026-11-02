#!/usr/bin/env python3
"""Score the gates against the director's interventions.

Two matching rules are reported, because they answer different questions.

  time-only  - the brief's rule: a speak-now event matches a help point when
               |t_speak - t_help| <= 10 min, whatever it was about. This is
               the generous reading and it flatters both gates: a stale-seat
               alarm that happens to land two minutes before a quota
               exhaustion counts as catching the quota.

  kind-aware - an event matches a help point only when it is in the +/-10 min
               window *and* its condition is one that could speak about that
               kind of problem (labels.SIGNALS). This is the strict reading:
               the gate has to notice the right thing, not just say something.

Each help point takes at most one event (the earliest, which gives it the best
"earlier" credit); each event matches at most one help point.

  TP = matched events, FP = unmatched events, FN = unmatched help points.
  precision = TP/(TP+FP), recall = TP/(TP+FN),
  false-positive rate = FP/(TP+FP)  (the share of speeches that were wrong).

Lead times are reported for the matched event, and separately for the earliest
kind-aware speech between the problem's onset and the director's action.

Usage: python3 scripts/score.py [--events data/events.json] [--out RESULT.json]
                                 [--sweep]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DATA, ROOT, WINDOW_END, WINDOW_START, local  # noqa: E402
from labels import EPISODES, KINDS  # noqa: E402

HELP_MIN = 10 * 60          # the brief's +/- 10 min
WINDOW_S = WINDOW_END - WINDOW_START
# the episode window runs from the problem's onset to the director's action:
# a speech before the problem began is not about this problem.


def match(events, episodes, kind_aware):
    """Greedy matching: the earliest event in the window wins each help point."""
    used = set()
    matches = {}
    for ep in episodes:
        best = None
        for i, e in enumerate(events):
            if i in used:
                continue
            if abs(e["t"] - ep["t_help"]) > HELP_MIN:
                continue
            if kind_aware and e["cond"] not in ep["signals"]:
                continue
            if best is None or e["t"] < events[best]["t"]:
                best = i
        if best is not None:
            used.add(best)
            matches[ep["id"]] = best
    return matches, used


def earliest_for(ep, events, kind_aware):
    """The earliest kind-aware speech between the onset and the director's action."""
    best = None
    for e in events:
        if not (ep["t_onset"] <= e["t"] <= ep["t_help"]):
            continue
        if kind_aware and e["cond"] not in ep["signals"]:
            continue
        if best is None or e["t"] < best["t"]:
            best = e
    return best


def score_gate(name, events, episodes, label=""):
    """Three matching rules, reported side by side.

    time_only - the brief's rule: any speech within +/-10 min of the help point.
    kind_aware - the same window, but the speech must be about the right kind of
                 problem.
    episode    - kind-aware, but the window runs from the problem's onset to the
                 director's action. This is the rule that answers the question the
                 experiment asks ("would the gate have caught it earlier?"): a
                 gate that speaks 2 h 42 m before the director acts is a better
                 catch, not a worse one, and the +/-10 min rule cannot see that.
    """
    out = {}
    for kind_aware in (False, True):
        matches, used = match(events, episodes, kind_aware)
        tp = len(matches)
        fp = len(events) - tp
        fn = len(episodes) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        hours = WINDOW_S / 3600.0

        per_ep = []
        lead_matched, stall_matched = [], []
        lead_early, stall_early = [], []
        for ep in episodes:
            idx = matches.get(ep["id"])
            row = {"id": ep["id"], "kind": ep["kind"], "t_help": local(ep["t_help"]),
                   "observable": ep["observable"], "caught": idx is not None}
            if idx is not None:
                e = events[idx]
                lead = ep["t_help"] - e["t"]
                cap = ep.get("cap_t", ep["t_help"])
                stall = min(ep["t_help"], cap) - e["t"]
                row.update({"matched_at": e["time"], "condition": e["cond"],
                            "seat": e.get("seat"), "lead_min": round(lead / 60.0, 1),
                            "stall_saved_min": round(stall / 60.0, 1)})
                lead_matched.append(lead / 60.0)
                stall_matched.append(stall / 60.0)
            ee = earliest_for(ep, events, kind_aware)
            if ee is not None:
                cap = ep.get("cap_t", ep["t_help"])
                lead = ep["t_help"] - ee["t"]
                stall = min(ep["t_help"], cap) - ee["t"]
                row.update({"earliest_at": ee["time"], "earliest_condition": ee["cond"],
                            "earliest_lead_min": round(lead / 60.0, 1),
                            "earliest_stall_saved_min": round(stall / 60.0, 1)})
                lead_early.append(lead / 60.0)
                stall_early.append(stall / 60.0)
            else:
                row.update({"earliest_at": None, "earliest_lead_min": None,
                            "earliest_stall_saved_min": None})
            per_ep.append(row)

        # recall over the episodes that the stream can speak about at all
        obs = [e for e in episodes if e["observable"]]
        caught_obs = sum(1 for e in obs if e["id"] in matches)

        by_kind = {}
        for kind in KINDS:
            eps = [e for e in episodes if e["kind"] == kind]
            caught = sum(1 for e in eps if e["id"] in matches)
            by_kind[kind] = {"episodes": len(eps), "caught": caught}

        key = "kind_aware" if kind_aware else "time_only"
        out[key] = {
            "speaks": len(events),
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4), "recall": round(recall, 4),
            "false_positive_rate": round(fpr_of(tp, fp), 4),
            "false_alarms_per_hour": round(fp / hours, 3),
            "speaks_per_hour": round(len(events) / hours, 3),
            "recall_over_observable": round(caught_obs / len(obs), 4) if obs else None,
            "observable_episodes": len(obs),
            "late_catches": sum(1 for x in lead_matched if x < 0),
            "lead_minutes_matched": {
                "n": len(lead_matched),
                "mean": round(sum(lead_matched) / len(lead_matched), 1) if lead_matched else None,
                "max": round(max(lead_matched), 1) if lead_matched else None},
            "stall_minutes_saved_matched": {
                "total": round(sum(stall_matched), 1),
                "mean": round(sum(stall_matched) / len(stall_matched), 1) if stall_matched else None},
            "lead_minutes_earliest": {
                "n": len(lead_early),
                "mean": round(sum(lead_early) / len(lead_early), 1) if lead_early else None,
                "max": round(max(lead_early), 1) if lead_early else None},
            "stall_minutes_saved_earliest": {
                "total": round(sum(stall_early), 1),
                "mean": round(sum(stall_early) / len(stall_early), 1) if stall_early else None},
            "by_kind": by_kind,
            "per_episode": per_ep,
        }
        if not kind_aware:
            out[key]["false_alarms"] = [
                {"t": e["time"], "condition": e["cond"], "seat": e.get("seat"),
                 "value": e.get("value")}
                for i, e in enumerate(events) if i not in used
            ] if len(events) <= 400 else f"omitted ({len(events)} events)"
    # ---- the episode rule -----------------------------------------------
    ep_used = set()
    ep_caught = {}
    for ep in episodes:
        best = None
        for i, e in enumerate(events):
            if i in ep_used:
                continue
            if e["cond"] not in ep["signals"]:
                continue
            if not (ep["t_onset"] <= e["t"] <= ep["t_help"]):
                continue
            if best is None or e["t"] < events[best]["t"]:
                best = i
        if best is not None:
            ep_used.add(best)
            ep_caught[ep["id"]] = best
    tp = len(ep_caught)
    fp = len(events) - tp
    fn = len(episodes) - tp
    hours = WINDOW_S / 3600.0
    per_ep = []
    lead_e, stall_e = [], []
    for ep in episodes:
        idx = ep_caught.get(ep["id"])
        row = {"id": ep["id"], "kind": ep["kind"], "t_help": local(ep["t_help"]),
               "observable": ep["observable"], "caught": idx is not None}
        if idx is not None:
            e = events[idx]
            cap = ep.get("cap_t", ep["t_help"])
            row.update({"matched_at": e["time"], "condition": e["cond"],
                        "lead_min": round((ep["t_help"] - e["t"]) / 60.0, 1),
                        "stall_saved_min": round((min(ep["t_help"], cap) - e["t"]) / 60.0, 1)})
            lead_e.append((ep["t_help"] - e["t"]) / 60.0)
            stall_e.append((min(ep["t_help"], cap) - e["t"]) / 60.0)
        per_ep.append(row)
    obs = [e for e in episodes if e["observable"]]
    out["episode"] = {
        "speaks": len(events), "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else 0.0,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else 0.0,
        "false_positive_rate": round(fpr_of(tp, fp), 4),
        "false_alarms_per_hour": round(fp / hours, 3),
        "recall_over_observable": round(
            sum(1 for e in obs if e["id"] in ep_caught) / len(obs), 4) if obs else None,
        "observable_episodes": len(obs),
        "lead_minutes": {"n": len(lead_e),
                         "mean": round(sum(lead_e) / len(lead_e), 1) if lead_e else None,
                         "max": round(max(lead_e), 1) if lead_e else None},
        "stall_minutes_saved": {"total": round(sum(stall_e), 1),
                                "mean": round(sum(stall_e) / len(stall_e), 1) if stall_e else None},
        "per_episode": per_ep,
    }
    out["gate"] = name
    out["label"] = label
    return out


def fpr_of(tp, fp):
    return fp / (tp + fp) if (tp + fp) else 0.0


def sweep(gates_mod, stream, params, episodes):
    """Sensitivity of the rate gate to its free thresholds."""
    out = []
    for label, key, values in (("memory rate GB/min", "mem_rate_gb_min",
                                (1.0, 2.0, 3.0, 4.0, 5.0, 6.0)),
                               ("wifi aborts / 5 min", "wifi_aborts_5min", (10, 15, 20, 25)),
                               ("api failures / 5 min", "api_burst_n", (1, 2, 3)),
                               ("queue growth / 10 min", "queue_growth", (2, 3, 4, 5))):
        for v in values:
            p = dict(params)
            p[key] = v
            ev = gates_mod.run_gate(stream, "b", p, WINDOW_START, WINDOW_END)
            s = score_gate("sweep", ev, episodes)["episode"]
            out.append({"parameter": key, "value": v, "speaks": s["speaks"], "tp": s["tp"],
                        "fp": s["fp"], "fn": s["fn"], "precision": s["precision"],
                        "recall": s["recall"], "false_positive_rate": s["false_positive_rate"],
                        "false_alarms_per_hour": s["false_alarms_per_hour"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", default=os.path.join(DATA, "events.json"))
    ap.add_argument("--out", default=os.path.join(ROOT, "RESULT.json"))
    ap.add_argument("--sweep", action="store_true", help="also run the threshold sweep")
    args = ap.parse_args()

    ev = json.load(open(args.events))
    episodes = sorted(EPISODES, key=lambda e: e["t_help"])

    result = {
        "experiment": "seat-watcher: would a time-first gate have caught 2026-11-01's "
                      "problems earlier and with fewer false alarms?",
        "day": "2026-11-01",
        "window": {"start": local(WINDOW_START), "end": local(WINDOW_END),
                   "hours": round(WINDOW_S / 3600.0, 2)},
        "labels": {
            "episodes": len(episodes), "kinds": KINDS,
            "help_point_window_min": HELP_MIN / 60,
            "definition": "one episode per director intervention: onset, the director's "
                          "first action (t_help, the point to beat), and the last action",
            "detail": [{"id": e["id"], "kind": e["kind"], "onset": local(e["t_onset"]),
                        "help": local(e["t_help"]), "end": local(e["t_end"]),
                        "what": e["what"], "source": e["source"],
                        "signals": e["signals"], "seats": e["seats"],
                        "observable": e["observable"]} for e in episodes]},
        "matching": {
            "time_only": "any speak-now event within +/-10 min of the help point",
            "kind_aware": "only a speak-now event whose condition could speak about that "
                          "kind of problem (labels.SIGNALS), within +/-10 min",
            "episode": "kind-aware, with the window running from the problem's onset to "
                       "the director's action - the rule that answers 'would it have "
                       "caught this earlier?'",
        },
        "gates": {},
    }

    for key, label in (("a", "level gate (a): output>45min, memory<25GB, disk<30GB"),
                       ("b", "rate gate (b): time-first"),
                       ("ab", "level + rate (c)"),
                       ("bplus", "rate + telemetry-dark (b+)"),
                       ("abplus", "level + rate + telemetry-dark (c+)"),
                       ("a_live", "level gate restricted to seats that are still alive (a')")):
        result["gates"][key] = score_gate(key, ev["gates"][key]["events"], episodes, label)

    if args.sweep:
        import gates as gates_mod
        stream = gates_mod.Stream(os.path.join(DATA, "stream.jsonl"))
        result["sensitivity"] = sweep(gates_mod, stream, ev["params"], episodes)

    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)
    print(f"wrote {args.out}\n")

    hdr = (f"{'gate':8s} {'rule':11s} {'speaks':>7s} {'TP':>3s} {'FP':>4s} {'FN':>3s} "
           f"{'prec':>6s} {'recall':>7s} {'FPR':>6s} {'FA/h':>6s} {'lead(m)':>8s} "
           f"{'stall(m)':>10s} {'early stall':>12s}")
    print(hdr)
    print("-" * len(hdr))
    for key in ("a", "b", "ab", "bplus", "abplus", "a_live"):
        g = result["gates"][key]
        for rule in ("time_only", "kind_aware", "episode"):
            r = g[rule]
            if rule == "episode":
                lm = r["lead_minutes"]["mean"] or 0
                st = r["stall_minutes_saved"]["total"]
            else:
                lm = r["lead_minutes_matched"]["mean"] or 0
                st = r["stall_minutes_saved_matched"]["total"]
            print(f"{key:8s} {rule:11s} {r['speaks']:7d} {r['tp']:3d} {r['fp']:4d} "
                  f"{r['fn']:3d} {r['precision']:6.3f} {r['recall']:7.3f} "
                  f"{r['false_positive_rate']:6.3f} {r['false_alarms_per_hour']:6.2f} "
                  f"{lm:8.1f} {st:10.1f}")


if __name__ == "__main__":
    main()
