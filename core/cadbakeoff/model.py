"""The cloud model, reached through the seat CLI.

The brief allows "GLM through zcode itself"; this box has no zcode and no
reachable cloud model with a usable API key, but it has the MiniMax Code CLI
signed in through the managed credential, so the model that writes the scripts
is a cloud model driven by the same agent binary a seat would use. That keeps
the rule that no LLM runs on the Thor: the CLI only carries text to a remote
API and brings the answer back.

Every call is one turn, with the tools turned off, so the answer is the
model's own text and the token counts are the provider's.

Two token numbers are kept, because they answer different questions:

``output_tokens``
    what the provider charged for the turn, reasoning included. This is the
    cost of the script to the cloud model.
``script_tokens``
    the extracted artefact alone, counted with a local tokenizer. This is the
    size of the script itself, and it is what the two languages are compared
    on.
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["CloudModel", "ModelReply", "extract_json", "extract_python", "count_tokens"]


@dataclass
class ModelReply:
    text: str
    output_tokens: int
    input_tokens: int
    duration_ms: int
    model: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "output_tokens": self.output_tokens,
            "input_tokens": self.input_tokens,
            "duration_ms": self.duration_ms,
        }


def _launcher() -> str:
    """The MiniMax Code launcher, found through the release pointer."""
    base = pathlib.Path.home() / ".minimax-code"
    release = (base / "current").read_text().strip()
    return str(base / "releases" / release / ".mcode-launcher")


class CloudModel:
    """One cloud model, one set of decoding parameters."""

    def __init__(
        self,
        model: str = "minimax/MiniMax-M3",
        *,
        launcher: str | None = None,
        timeout: int = 600,
        extra_args: list[str] | None = None,
    ) -> None:
        self.model = model
        self.launcher = launcher or _launcher()
        self.timeout = timeout
        self.extra_args = extra_args or []

    def call(self, prompt: str, *, system: str | None = None) -> ModelReply:
        # The CLI can write the turn's last message to a file, and that file is
        # the primary source of the reply: the JSON result's ``output`` field
        # is empty on the turns where the model spends its budget on a tool
        # call instead of on an answer, and on those turns the last message is
        # still on disk. The JSON is the fallback.
        last = pathlib.Path(tempfile.gettempdir()) / f"cadbakeoff-last-{time.time_ns()}.txt"
        cmd = [
            self.launcher,
            "exec",
            "--permission",
            "off",
            "--max-steps",
            "1",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--timeout",
            f"{self.timeout}s",
            "--output-last-message",
            str(last),
            *self.extra_args,
        ]
        if system:
            cmd += ["--system-prompt", system]
        cmd.append(prompt)
        started = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 60)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        stdout = proc.stdout.strip()
        if not stdout:
            raise RuntimeError(f"model call failed (rc={proc.returncode}): {proc.stderr[:800]}")
        # The CLI prints the exec result as JSON; some builds prefix a banner.
        start = stdout.find("{")
        if start < 0:
            raise RuntimeError(f"no JSON in the model reply: {stdout[:400]}")
        payload = json.loads(stdout[start:])
        text = payload.get("output") or ""
        if not text and last.exists():
            text = last.read_text(errors="replace")
        last.unlink(missing_ok=True)
        usage = payload.get("usage") or {}
        model_info = payload.get("model") or {}
        return ModelReply(
            text=text,
            output_tokens=int(usage.get("outputTokens") or 0),
            input_tokens=int(usage.get("inputTokens") or 0),
            duration_ms=int(payload.get("durationMs") or elapsed_ms),
            model=f"{model_info.get('providerId')}/{model_info.get('modelId')}",
            provider=str(model_info.get("providerKind") or ""),
            raw=payload,
        )


# ---------------------------------------------------------------------------
# artefact extraction
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\s*\n(.*?)(?:\n```|\Z)", re.DOTALL)


def _strip_fences(text: str) -> str:
    match = _FENCE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def extract_json(text: str) -> tuple[str | None, str | None]:
    """Pull the JSON object out of a reply.

    Returns ``(payload_text, error)``: the parsed JSON re-serialised, or the
    reason it could not be read.
    """
    body = _strip_fences(text)
    start = body.find("{")
    if start < 0:
        return None, "no JSON object in the reply"
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(body)):
        ch = body[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        return None, "the JSON object in the reply is not closed"
    chunk = body[start:end]
    try:
        parsed = json.loads(chunk)
    except json.JSONDecodeError as exc:
        return None, f"the JSON in the reply does not parse: {exc}"
    return json.dumps(parsed, indent=1), None


def extract_python(text: str) -> tuple[str | None, str | None]:
    """Pull the Python module out of a reply."""
    body = _strip_fences(text)
    if not body.strip():
        return None, "the reply is empty"
    try:
        compile(body, "<reply>", "exec")
    except SyntaxError as exc:
        return None, f"the Python in the reply does not parse: {exc}"
    return body, None


def count_tokens(text: str) -> int:
    """A local token count for the artefact alone.

    ``tiktoken``'s ``cl100k_base`` is a proxy for any particular model's
    tokenizer; it is used because it is the same proxy for both kernels, so
    the comparison between the two languages is fair even though the absolute
    number is not this model's own tokenizer.
    """
    try:
        import tiktoken  # type: ignore

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # A stable fallback: four characters per token, the usual rule of thumb.
        return max(1, (len(text) + 3) // 4)
