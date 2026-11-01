"""The generation stage: one cloud-model call per prop per kernel.

Both arms get the same prompt apart from the output-format block, the same
model and the same decoding settings. The reply is saved next to the artefact
so the run can be replayed without spending another call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import time

from core.cadbakeoff.model import CloudModel, count_tokens, extract_json, extract_python
from core.cadbakeoff.prompts import build_prompt
from core.cadbakeoff.specs import PROP_NAMES

#: The system prompt both arms get. It replaces the agent's own identity so
#: the model sees a plain instruction and a plain answer, and it is the same
#: string for both kernels.
SYSTEM = (
    "You are a CAD script generator. You answer with the artefact the user asks "
    "for and nothing else. You never use tools. You never explain. You never "
    "wrap the artefact in a markdown fence unless asked."
)

#: The decoding settings both arms get.
#:
#: One turn, no tools. The task is "write this artefact", so a single
#: assistant step is the whole protocol: the model either writes the file or
#: it does not. Letting the turn run for several steps lets the model spend
#: them on tool calls instead of on the artefact, and a turn that ends on a
#: tool call has no reply to read — which is what the ladder and the table
#: hit before this was pinned to one step. Every artefact in the bakeoff is
#: generated with exactly this setting, for both kernels.
EXTRA_ARGS: list[str] = []

#: How many times a prop is re-asked when the reply did not come back whole.
#: A truncated reply is a transport problem, not a prop problem, so it is
#: re-asked rather than counted against the kernel. The budget is the same
#: for both kernels, and the number of attempts each artefact took is kept in
#: the replies file, so the transport's own flakiness is visible in the
#: report rather than hidden inside it.
RETRIES = 10

#: The wait between two attempts, in seconds. The cloud model is reached
#: through a seat credential that other seats on this box hold too, and a
#: turn that lands on top of somebody else's ends without a reply. A pause
#: between attempts makes the next turn land on its own.
BACKOFF_SECONDS = (5, 10, 15, 25, 40, 60, 60, 60, 60, 60)


def artifact_path(out_dir: pathlib.Path, prop: str, kernel: str) -> pathlib.Path:
    suffix = ".json" if kernel == "solidcraft" else ".py"
    return out_dir / f"{prop}.{kernel}{suffix}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="~/lm-wt/cad-bakeoff/out/gen")
    parser.add_argument("--records", default=None, help="the replies file (default: <out>/replies.json)")
    parser.add_argument("--props", nargs="*", default=list(PROP_NAMES))
    parser.add_argument("--kernels", nargs="*", default=["solidcraft", "build123d"])
    parser.add_argument("--model", default="minimax/MiniMax-M3")
    parser.add_argument("--only", nargs="*", default=None, help="prop.kernel pairs to redo")
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    records_path = pathlib.Path(args.records).expanduser() if args.records else out_dir / "replies.json"
    records: dict[str, dict] = {}
    if records_path.exists():
        records = json.loads(records_path.read_text())

    model = CloudModel(model=args.model, extra_args=EXTRA_ARGS)
    for prop in args.props:
        for kernel in args.kernels:
            key = f"{prop}.{kernel}"
            if args.only and key not in args.only:
                continue
            path = artifact_path(out_dir, prop, kernel)
            if path.exists() and key in records:
                print(f"skip {key} (already generated)")
                continue
            prompt = build_prompt(prop, kernel)
            started = time.monotonic()
            # The prompt is kept next to the artefact, so the run can be shown
            # to have given the two arms the same brief.
            (out_dir / f"{prop}.{kernel}.prompt.txt").write_text(prompt)
            record: dict = {"prop": prop, "kernel": kernel, "prompt_chars": len(prompt)}
            record["prompt_sha256"] = hashlib.sha256(prompt.encode()).hexdigest()
            payload = None
            error: str | None = None
            for attempt in range(RETRIES):
                try:
                    reply = model.call(prompt, system=SYSTEM)
                except Exception as exc:  # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
                    record["status"] = "call_failed"
                    continue
                if kernel == "solidcraft":
                    payload, error = extract_json(reply.text)
                else:
                    payload, error = extract_python(reply.text)
                record.update(
                    {
                        "model": reply.model,
                        "provider": reply.provider,
                        "status": reply.raw.get("status"),
                        "output_tokens": reply.output_tokens,
                        "input_tokens": reply.input_tokens,
                        "duration_ms": reply.duration_ms,
                        "reply_chars": len(reply.text),
                        "attempt": attempt + 1,
                    }
                )
                if payload is not None:
                    break
                # A truncated or empty reply is a transport problem: wait a
                # little and ask again.
                if attempt + 1 < RETRIES:
                    pause = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                    record["backoff_seconds"] = pause
                    time.sleep(pause)
            record["wall_ms"] = int((time.monotonic() - started) * 1000)
            record["extract_error"] = error
            if payload is not None:
                path.write_text(payload)
                record["artifact"] = str(path)
                record["script_tokens"] = count_tokens(payload)
                record["script_chars"] = len(payload)
            records[key] = record
            records_path.write_text(json.dumps(records, indent=1))
            print(
                f"{key}: {record.get('status')} out={record.get('output_tokens')} "
                f"script_tokens={record.get('script_tokens')} error={error}",
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
