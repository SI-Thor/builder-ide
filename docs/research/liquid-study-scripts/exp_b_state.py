"""EXP B -- does llama.cpp expose the d1 hidden / recurrent state?

The brief asks for this check, and the chats wanted "state snapshots" for two
different purposes that have different answers:

  (1) snapshot / restore / FORK a decision context -- i.e. freeze the exact
      model state behind a decision so you can branch it;
  (2) ship the model's internal hidden state to the cloud to calibrate
      against -- i.e. read the numbers out.

llama.cpp's server has a first-class mechanism for (1): started with
`--slot-save-path`, POST /slots/{id}?action=save|restore|erase writes and
reads a slot file containing the llama context state. For a hybrid model
(LFM2 is conv + SSM + attention) that state covers the recurrent memory as
well as the KV cache -- but it is an opaque binary blob, not an exported
tensor. For (2) there is, as far as this box shows, no endpoint at all: the
only numeric output of a decision is the per-option score vector.

This script establishes which of the two is real, empirically, on d1-3B Q8.

Coordination with lab-cascade: their E3 asks for "a cached prefix state per
task" as a lever to *use*. This script asks the prior question -- does the
mechanism exist, and is it exact -- and produces the snapshot artefact that
E3 would consume. It runs no accuracy task and no precision ladder.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d1lab import (LAB, Server, box_state, decide, get_json, stats, warm_gpu,
                    write_result)

MODEL = "d1-3B"
PRECISION = "Q8"
PORT = 8291
PORT_CACHE = 8292
SAVE_DIR = LAB / "state"

QUESTION = {
    "where": {
        "type": "choice",
        "instructions": "Where is the best water to be working right now?",
        "criteria": {
            "A": "the shallow water off the north point where the fish are showing",
            "B": "the deep water past the bank where the birds are working",
            "C": "the slack corner inside the harbour mouth",
            "D": "the tide race where the two currents meet",
            "E": "under the kelp beds along the ledge",
        },
    }
}
QUESTION2 = {
    "tide": {
        "type": "choice",
        "instructions": "How should the skipper read the tide from this state?",
        "criteria": {
            "A": "the tide is running hard and will not slacken for hours",
            "B": "the tide is nearly slack and the water is at its calmest",
            "C": "the tide is flooding and the channel is filling fast",
            "D": "the tide cannot be read from this state at all",
            "E": "the tide is ebbing and the current is still strong",
        },
    }
}

STATE_A = ("A lone rowboat is tied to a weathered post at the north dock. The tide is high and "
           "the channel runs fast past the mooring. A school of small silver fish is visible in "
           "the shallow water off the point, and the light is flat and grey.")
STATE_B = ("Deep water beyond the bank, clean swell rolling from the southwest, and a long line "
           "of birds working a seam a few hundred yards off the bow. The deck is wet and "
           "everything stays quiet.")
#: a much longer state, to see how the saved slot file scales with the prompt
STATE_LONG = (" ".join([STATE_A] * 12))


def probs(body: dict, qid: str = "where") -> dict:
    return body["answers"][qid]["probabilities"]


def same(a: dict, b: dict, tol: float = 0.0) -> bool:
    if set(a) != set(b):
        return False
    return all(abs(float(a[k]) - float(b[k])) <= tol for k in a)


def slots_post(url: str, id_slot: int, action: str, filename: str) -> tuple[int, dict]:
    from d1lab import _post
    st, body, _ = _post(url, f"/slots/{id_slot}?action={action}", {"filename": filename},
                        method="POST")
    return st, body


def probe_interface(url: str) -> dict:
    """What does the server expose about a decision? This is the (2) answer."""
    probes = {}
    for path in ("/props", "/slots", "/metrics", "/v1/models"):
        st, body = get_json(url, path)
        entry = {"status": st}
        if path == "/props" and st == 200 and isinstance(body, dict):
            entry["keys"] = sorted(k for k in body.keys()
                                   if any(t in k.lower() for t in
                                          ("decis", "state", "slot", "model", "cache")))
            entry["model"] = body.get("model_path") or body.get("model")
        elif path == "/slots" and st == 200 and isinstance(body, list) and body:
            s0 = body[0]
            entry["slot0_keys"] = sorted(s0.keys()) if isinstance(s0, dict) else None
            if isinstance(s0, dict):
                entry["slot0_n_prompt_tokens"] = s0.get("n_prompt_tokens")
                entry["slot0_n_prompt_tokens_cache"] = s0.get("n_prompt_tokens_cache")
            entry["slot0_state_keys"] = (sorted(s0.get("state", {}).keys())
                                         if isinstance(s0, dict) and isinstance(s0.get("state"), dict) else None)
        probes[path] = entry
    # is there any endpoint that hands out internal activations?
    st, body, _ = decide(url, STATE_A, QUESTION)
    probes["decision_response_shape"] = {
        "status": st,
        "top_level_keys": sorted(body.keys()),
        "answer_keys": sorted(body["answers"]["where"].keys()),
        "usage_keys": sorted(body["usage"].keys()),
        "has_hidden_state": any(k in json.dumps(body).lower()
                                 for k in ("hidden", "embedding", "logits", "activation")),
    }
    return probes


def main() -> int:
    out = {
        "experiment": "exp_b_state",
        "question": "does llama.cpp expose the d1 hidden or recurrent state, and exactly?",
        "model": MODEL, "precision": PRECISION,
        "decision_type": "lfm2-d1 (LFM2 hybrid: conv + SSM + attention)",
        "port": PORT,
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "box_at_start": box_state(),
    }

    if SAVE_DIR.exists():
        shutil.rmtree(SAVE_DIR)
    SAVE_DIR.mkdir(parents=True, exist_ok=True)

    srv = Server(model=MODEL, precision=PRECISION, port=PORT,
                 extra_args=["--slot-save-path", str(SAVE_DIR), "--slots"])
    srv.start()
    out["server_log"] = str(srv.log)
    try:
        warm_gpu(srv.url, QUESTION, seconds=3.0)

        out["interface_probe"] = probe_interface(srv.url)

        # --- (1) snapshot / restore / fork ------------------------------
        st, body_a1, _ = decide(srv.url, STATE_A, QUESTION)
        if st != 200:
            raise RuntimeError(body_a1)
        out["a_first"] = {"status": st, "probabilities": probs(body_a1)}

        # snapshot the slot (it now holds state A's context)
        st, res = slots_post(srv.url, 0, "save", "state_a.bin")
        out["save_a"] = {"status": st, "response": res}
        f_a = SAVE_DIR / "state_a.bin"
        out["save_a"]["file_exists"] = f_a.exists()
        out["save_a"]["file_bytes"] = f_a.stat().st_size if f_a.exists() else None

        # move the slot on to a different state
        st, body_b, _ = decide(srv.url, STATE_B, QUESTION)
        out["b_on_same_slot"] = {"status": st, "probabilities": probs(body_b)}

        # restore the snapshot, then ask again
        st, res = slots_post(srv.url, 0, "restore", "state_a.bin")
        out["restore_a"] = {"status": st, "response": res}
        st, body_a2, _ = decide(srv.url, STATE_A, QUESTION)
        out["a_after_restore"] = {"status": st, "probabilities": probs(body_a2)}

        out["restore_exactness"] = {
            "a_first_vs_a_after_restore_bit_identical": same(probs(body_a1), probs(body_a2), 0.0),
            "max_abs_diff": round(max(abs(float(probs(body_a1)[k]) - float(probs(body_a2)[k]))
                                      for k in probs(body_a1)), 9),
            "a_after_restore_vs_b_on_same_slot_bit_identical": same(probs(body_a2), probs(body_b), 0.0),
        }

        # fork: restore the snapshot, ask a DIFFERENT question from that
        # restored context, then restore again and ask the same one.
        slots_post(srv.url, 0, "restore", "state_a.bin")
        st, fork1, _ = decide(srv.url, STATE_A, QUESTION2)
        slots_post(srv.url, 0, "restore", "state_a.bin")
        st, fork2, _ = decide(srv.url, STATE_A, QUESTION2)
        out["fork"] = {
            "status": st,
            "probabilities_1": probs(fork1, "tide"),
            "probabilities_2": probs(fork2, "tide"),
            "bit_identical_across_forks": same(probs(fork1, "tide"), probs(fork2, "tide"), 0.0),
        }

        # how does the saved blob scale with prompt length?
        slots_post(srv.url, 0, "restore", "state_a.bin")
        st, _, _ = decide(srv.url, STATE_LONG, QUESTION)
        slots_post(srv.url, 0, "save", "state_long.bin")
        f_l = SAVE_DIR / "state_long.bin"
        size_a = f_a.stat().st_size if f_a.exists() else None
        size_l = f_l.stat().st_size if f_l.exists() else None
        # a second save of the same short state: is the blob deterministic?
        slots_post(srv.url, 0, "restore", "state_a.bin")
        slots_post(srv.url, 0, "save", "state_a2.bin")
        f_a2 = SAVE_DIR / "state_a2.bin"
        out["blob"] = {
            "bytes_state_a": size_a,
            "bytes_state_long": size_l,
            "bytes_state_a_saved_again": f_a2.stat().st_size if f_a2.exists() else None,
            "same_state_two_saves_identical_bytes": (
                f_a.read_bytes() == f_a2.read_bytes()) if (f_a.exists() and f_a2.exists()) else None,
            "first_16_bytes_hex": f_a.read_bytes()[:16].hex() if f_a.exists() else None,
            "contains_prompt_as_plain_text": (
                STATE_A.split(" ")[0].encode() in f_a.read_bytes()) if f_a.exists() else None,
        }
    finally:
        srv.stop()

    # --- the runtime's own state cache ----------------------------------
    # `--cache-ram` is opt-in for decision models ("decision model: prompt
    # cache disabled by default, use --cache-ram N to enable it"). Does it
    # actually restore a decision model's state, and what does it buy?
    cache = {"port": PORT_CACHE, "cache_ram_mib": 256}
    srv2 = Server(model=MODEL, precision=PRECISION, port=PORT_CACHE,
                  extra_args=["--cache-ram", "256", "--slots"])
    srv2.start()
    cache["server_log"] = str(srv2.log)
    try:
        warm_gpu(srv2.url, QUESTION, seconds=3.0)
        seq = [STATE_A, STATE_B, STATE_A, STATE_A]
        walls = []
        for s in seq:
            st, body, secs = decide(srv2.url, s, QUESTION)
            walls.append(round(secs * 1000, 2))
        cache["sequence"] = ["A", "B", "A", "A"]
        cache["latency_ms"] = walls
        cache["latency_stats_ms"] = stats(walls)
        log = Path(srv2.log).read_text(errors="replace")
        cache["log_has_found_better_prompt"] = "found better prompt" in log
        cache["log_mentions_cache"] = [ln.strip() for ln in log.splitlines()
                                       if "cache" in ln.lower()][:8]
        st, body, _ = decide(srv2.url, STATE_A, QUESTION)
        cache["a_repeat_probabilities"] = probs(body) if st == 200 else None
    finally:
        srv2.stop()

    out["prompt_cache"] = cache
    out["box_at_end"] = box_state()
    out["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")

    p = write_result("exp_b_state.json", out)
    print(json.dumps({
        "restore_exactness": out.get("restore_exactness"),
        "fork": out.get("fork"),
        "blob": out.get("blob"),
        "interface_probe": out.get("interface_probe"),
        "prompt_cache": {k: v for k, v in cache.items() if k != "log_mentions_cache"},
    }, indent=2))
    print(f"\nwrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
