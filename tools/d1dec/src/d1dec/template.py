"""The d1 decision prompt, exactly as llama.cpp builds it.

Three steps, in this order, all of them taken from llama.cpp's
``server_decision_context``:

1. **parse the wire question** into options — ``choice`` keeps the
   criteria object's order, ``score`` numbers its levels from ``0``, and
   ``noul`` is ``true`` first (the d1 models were trained with the true
   option first);
2. **break the quoted spellings** — the texts of the control tokens are
   cut with a zero-width space so they stay text in the state and in the
   instructions;
3. **render the model's own template** — ``tokenizer.chat_template.systemone``
   out of the GGUF, with Jinja, so the prompt is the model's and not a
   copy of it.

The label codes are the ones of ``prompt.py`` in the model repo: ``A``,
``B``, ``C``… for a choice, the level number for a score, and
``true``/``false`` for a noul.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The zero-width space llama.cpp puts after the first character of a
#: quoted control token (U+200B).
ZWSP = "\u200b"


@dataclass
class Option:
    key: str
    description: str | None
    label: str = ""


@dataclass
class WireQuestion:
    id: str
    type: str  # "choice" | "score" | "noul"
    instructions: str
    options: list[Option] = field(default_factory=list)


def parse_question(qid: str, q: dict[str, Any]) -> WireQuestion:
    """One question of the ``/v1/systemone`` wire body."""
    qtype = q.get("type", "")
    instructions = q.get("instructions", "")
    criteria = q.get("criteria", None)
    options: list[Option] = []
    if qtype == "choice":
        if not isinstance(criteria, dict) or not criteria:
            raise ValueError(f"questions.{qid}: \"criteria\" must be a non-empty object")
        for key, desc in criteria.items():
            options.append(Option(key=key, description=desc))
    elif qtype == "score":
        if not isinstance(criteria, list) or not (2 <= len(criteria) <= 10):
            raise ValueError(f"questions.{qid}: \"criteria\" must be an array of 2 to 10 levels")
        for i, desc in enumerate(criteria):
            options.append(Option(key=str(i), description=desc))
    elif qtype == "noul":
        if criteria is not None and not isinstance(criteria, dict):
            raise ValueError(f"questions.{qid}: \"criteria\" must be an object")
        criteria = criteria or {}
        desc_false = criteria.get("false")
        desc_true = criteria.get("true")
        # the d1 models read "true" first
        options = [Option(key="true", description=desc_true), Option(key="false", description=desc_false)]
    else:
        raise ValueError(f"questions.{qid}: \"type\" must be one of: choice, score, noul")
    return WireQuestion(id=qid, type=qtype, instructions=instructions, options=options)


class QuotedSpellings:
    """The texts of the control tokens, and the breaking they need.

    A control token's text in the state or in the instructions would be
    tokenised as the token itself, so a zero-width space is put after its
    first character. llama.cpp does this for every control token of two
    bytes or more, longest first (``init_quoted_spellings``), and then
    breaks the text *repeatedly*, because the break can create a new
    match that overlapped the one broken before it.

    The scan is done on bytes, like llama.cpp's, because a spelling is
    matched at a byte offset.
    """

    def __init__(self, tokens: list[str], token_types: list[int]) -> None:
        spellings = [
            t
            for t, ty in zip(tokens, token_types)
            if ty == 3 and len(t.encode("utf-8")) >= 2  # 3 == CONTROL
        ]
        spellings.sort(key=lambda s: len(s.encode("utf-8")), reverse=True)
        self.spellings = spellings
        self._spellings_b = [s.encode("utf-8") for s in spellings]
        self._first_bytes = {s[0] for s in self._spellings_b}

    def break_text(self, text: str) -> str:
        """``d1_break``: break the quoted spellings, until nothing changes."""
        cur = text.encode("utf-8")
        zwsp = ZWSP.encode("utf-8")
        changed = True
        while changed:
            changed = False
            out = bytearray()
            i = 0
            n = len(cur)
            while i < n:
                hit = None
                if cur[i] in self._first_bytes:
                    for spelling in self._spellings_b:
                        if cur[i : i + len(spelling)] == spelling:
                            hit = spelling
                            break
                if hit is None:
                    out.append(cur[i])
                    i += 1
                    continue
                # after the first byte, the rest of the spelling
                out += hit[:1] + zwsp + hit[1:]
                i += len(hit)
                changed = True
            cur = bytes(out)
        return cur.decode("utf-8")


class PromptBuilder:
    """Turns a wire body into the prompt and the label groups."""

    def __init__(self, template_src: str, quoted: QuotedSpellings) -> None:
        from jinja2 import Environment

        self.env = Environment(autoescape=False, keep_trailing_newline=True)
        self.template = self.env.from_string(template_src)
        self.quoted = quoted

    # -- the pieces ----------------------------------------------------------

    def _escape(self, value: Any) -> Any:
        """``decision_escape``: the break applied to every string."""
        if isinstance(value, str):
            return self.quoted.break_text(value)
        if isinstance(value, list):
            return [self._escape(v) for v in value]
        if isinstance(value, dict):
            return {self._escape(k): self._escape(v) for k, v in value.items()}
        return value

    def labels_for(self, q: WireQuestion, tokenizer) -> tuple[list[str], list[list[int]]]:
        """The label texts and their token groups.

        Each group is the set of tokens whose logit is read for that
        option; the option's score is the maximum over its group.
        """
        if q.type != "choice":
            texts: list[str] = []
            groups: list[list[int]] = []
            for opt in q.options:
                if q.type == "score":
                    forms = [opt.key]
                elif opt.key == "true":
                    forms = ["yes", "Yes", "YES"]
                else:
                    forms = ["no", "No", "NO"]
                group = _single_tokens(tokenizer, forms)
                if not group:
                    raise ValueError(f"decision label is not a single token: {opt.key}")
                texts.append(opt.key)
                groups.append(group)
            return texts, groups

        n_options = len(q.options)
        is_letters = all(len(o.key) == 1 and o.key.isalpha() for o in q.options)
        codes: list[str] = []
        for i in range(n_options):
            if is_letters:
                codes.append(q.options[i].key)
            elif n_options <= 26:
                codes.append(chr(ord("A") + i))
            else:
                codes.append(chr(ord("A") + i - 26) + chr(ord("A") + (i - 26) % 26))

        pool: list[str] = [chr(c) for c in range(ord("A"), ord("Z") + 1)]
        pool += [f"{i:02d}" for i in range(100)]
        pool += [chr(c) for c in range(ord("a"), ord("z") + 1)]
        pool += [f"#{i}" for i in range(200)]
        pool += [a + b for a in [chr(c) for c in range(ord("A"), ord("Z") + 1)] for b in [chr(c) for c in range(ord("A"), ord("Z") + 1)]]

        used: set[int] = set()
        texts = []
        groups = []
        for code in codes:
            group = _take_group(tokenizer, code, used)
            if group is None:
                for cand in pool:
                    group = _take_group(tokenizer, cand, used)
                    if group is not None:
                        break
            if group is None:
                raise ValueError(f"no single-token label left for {n_options} options")
            texts.append(code)
            groups.append(group)
        return texts, groups

    # -- the prompt ----------------------------------------------------------

    def build(
        self,
        state: str | None,
        question: WireQuestion,
        tokenizer,
    ) -> tuple[str, list[str], list[list[int]]]:
        """The prompt of one question, and its label texts and groups."""
        texts, groups = self.labels_for(question, tokenizer)
        for opt, text in zip(question.options, texts):
            opt.label = text

        inp: dict[str, Any] = {
            "id": question.id,
            "type": question.type,
            "instructions": question.instructions,
            "state": state,
            "options": [
                {"key": o.key, "description": o.description, "label": o.label} for o in question.options
            ],
        }
        inp = self._escape(inp)
        inp["images"] = []
        prompt = self.template.render(**inp)
        return prompt, texts, groups


def _single_tokens(tokenizer, forms: list[str]) -> list[int]:
    """The ids of the forms that are exactly one token, without repeats."""
    out: list[int] = []
    for form in forms:
        toks = tokenizer.encode(form, parse_special=False)
        if len(toks) == 1 and toks[0] not in out:
            out.append(toks[0])
    return out


def _take_group(tokenizer, code: str, used: set[int]) -> list[int] | None:
    """The label group of a code: the code, and the code with a space."""
    toks = tokenizer.encode(code, parse_special=False)
    if len(toks) != 1 or toks[0] in used:
        return None
    used.add(toks[0])
    group = [toks[0]]
    for tok in _single_tokens(tokenizer, [" " + code]):
        if tok != toks[0]:
            group.append(tok)
    return group
