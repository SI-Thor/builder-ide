#!/usr/bin/env python3
"""The ghost's second look: one cloud VLM call on the prop's own renders.

The plausibility prior's ghost gate is a rank against a group — "this
resembles nothing the night knows" — and a rank can be wrong. The
night-v5 letter's open question was what to do with a ghost; the answer
this implements is *ask once more, elsewhere*: the prop's mesh is rendered
from three views (`render_prop_views.py`, beside this script) and one
DeepInfra vision call looks at the renders and answers the fixed question
— is this a well-formed example of the kind, or a degenerate shape? The
prop drops only if the second look agrees with the prior; both verdicts
ride one `night.ghost_second_look` row in the ledger.

One call, fixed words, greedy decoding (temperature 0): the same prop and
the same renders give the same verdict twice, so the row is reproducible.
If the call cannot answer (no key, wire down, no GLB to render), the
second look did not agree, and the prop is kept — degraded, with the
error on the row. "Drop only if the second look agrees" is the rule; a
silent wire is not agreement.

Importable (the night's prop critic calls `second_look`) and a CLI (the
probe on a run's own ghost):

    PYTHONPATH=. ~/lm-wt/propmaker-batch/.venv/bin/python \
        docs/lab/night-v6-scripts/second_look.py \
        --glb ~/lm-wt/trellis/out/genbatch/lantern_s1205_00007_.glb \
        --prompt "a brass lantern" --outdir /tmp/ghost-views
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core.voyager.llm import DEEPINFRA_BASE_URL, load_secret  # noqa: E402

#: The v2 venv's python — the one whose bpy both the scene export and the
#: prop renders run under.
V2_PYTHON = Path.home() / "lm-wt" / "v2-thor" / ".venv" / "bin" / "python"

#: The second look's model: a vision model on DeepInfra, small enough to
#: answer one question in seconds and capable enough to tell a lantern
#: from a block. Named here, not hidden in a default: the model is the
#: caller's decision (the local VLM candidate's rule, B2, one seat over).
GHOST_VLM_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct"

#: The fixed question. "{prompt}" is the request's own concept words.
GHOST_QUESTION = (
    "The night's plausibility prior says this 3D object resembles nothing "
    "it knows — for example a solid block filling its shape's bounding "
    "box, a blank, or a blob. The images are renders of the object's mesh "
    "from three views. Is the object a real, well-formed {prompt}, with "
    "the openings, parts and proportions such an object should have? "
    "Answer with one word first — Yes or No — then one short sentence "
    "saying why."
)


def _encode_image(image: str | Path) -> str:
    data = Path(image).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def _says_yes(answer: str) -> bool:
    """The rule the local VLM critic uses: anything that does not say yes
    is a no (core.critic.candidates.vlm._is_yes)."""
    text = answer.strip().lower()
    if not text:
        return False
    if text.startswith("yes"):
        return True
    if text.startswith("no"):
        return False
    for word in text.replace(",", " ").replace(".", " ").split():
        if word in ("yes", "no"):
            return word == "yes"
    return False


def ask_deepinfra_vlm(
    images: Sequence[Path],
    question: str,
    *,
    model: str = GHOST_VLM_MODEL,
    timeout: float = 180.0,
    max_tokens: int = 512,
) -> tuple[str, dict[str, Any], float]:
    """One call, greedy. Returns (answer, usage, wall seconds); raises
    RuntimeError with the wire's own words when the wire would not answer."""
    key = load_secret("DEEPINFRA_API_KEY") or load_secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "no DeepInfra key in ~/.config/last-mile/secrets.env")
    body = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                *[{"type": "image_url",
                   "image_url": {"url": _encode_image(image)}}
                  for image in images],
            ],
        }],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "top_p": 1.0,
    }
    request = urllib.request.Request(
        f"{DEEPINFRA_BASE_URL}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"deepinfra returned HTTP {exc.code}") from exc
    except Exception as exc:  # network, timeout, bad JSON
        raise RuntimeError(f"deepinfra call failed: {exc}") from exc
    wall = time.perf_counter() - started
    message = (payload.get("choices") or [{}])[0].get("message") or {}
    return (message.get("content") or "").strip(), payload.get("usage") or {}, wall


def render_prop_views(glb: Path, outdir: Path, timeout: float = 600.0
                      ) -> dict[str, Any]:
    """The prop's mesh from three views, under the v2 venv's bpy.

    The child runs with a scrubbed environment: the parent's
    ``PYTHONPATH`` (the repo, under the propmaker venv) segfaults the v2
    bpy's Cycles — measured on this box, rc -11 with the parent's env and
    a clean 7.8 s render without it.
    """
    import subprocess  # noqa: PLC0415

    script = Path(__file__).resolve().parent / "render_prop_views.py"
    env = {"HOME": str(Path.home()), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    result = subprocess.run(
        [str(V2_PYTHON), str(script), "--glb", str(glb),
         "--outdir", str(outdir)],
        capture_output=True, text=True, timeout=timeout, env=env)
    stats_path = outdir / "render_stats.json"
    if result.returncode != 0 and not stats_path.exists():
        return {"ok": False,
                "error": (result.stderr or result.stdout)[-400:]}
    if not stats_path.exists():
        return {"ok": False,
                "error": "the renderer wrote no render_stats.json"}
    stats = json.loads(stats_path.read_text())
    if result.returncode != 0:
        stats["renderer_exit_code"] = result.returncode
    return {"ok": True, **stats,
            "views": [str(outdir / name) for name in stats["views"]]}


def second_look(*, prompt: str, glb: Path, outdir: Path,
                model: str = GHOST_VLM_MODEL) -> dict[str, Any]:
    """Both verdicts on one ghost: render the mesh, ask the cloud once.

    The row the caller records: `prior_verdict` is the caller's to add
    (the prior said ghost before this ran); everything here is the second
    look itself — the renders' triangles and wall, the model, the answer's
    first 400 characters, the usage, and `cloud_ghost`: True when the
    cloud *agrees* the object is degenerate (it did not say yes to
    "well-formed").
    """
    outdir.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"model": model, "prompt": prompt}
    renders = render_prop_views(glb, outdir)
    row["renders"] = {key: value for key, value in renders.items()
                      if key != "views"}
    if not renders.get("ok"):
        row.update({"ok": False, "error": renders.get("error"),
                    "cloud_ghost": None})
        return row
    row["render_paths"] = renders["views"]
    question = GHOST_QUESTION.format(prompt=prompt or "object")
    try:
        answer, usage, wall = ask_deepinfra_vlm(renders["views"], question,
                                                model=model)
    except RuntimeError as exc:
        row.update({"ok": False, "error": str(exc)[:300],
                    "cloud_ghost": None})
        return row
    if not answer:
        row.update({"ok": False, "error": "the model answered nothing",
                    "cloud_ghost": None})
        return row
    row.update({
        "ok": True,
        "answer": answer[:400],
        "usage": usage,
        "wall_s": round(wall, 2),
        "cloud_ghost": not _says_yes(answer),
    })
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--glb", type=Path, required=True)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--model", default=GHOST_VLM_MODEL)
    args = parser.parse_args()
    row = second_look(prompt=args.prompt, glb=args.glb, outdir=args.outdir,
                      model=args.model)
    row["prior_verdict"] = "ghost"
    print(json.dumps(row, indent=2))
    return 0 if row.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
