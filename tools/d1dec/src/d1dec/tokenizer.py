"""The d1 (LFM3) tokenizer, reproduced from the GGUF.

The model's own metadata says ``tokenizer.ggml.model = gpt2`` with
``tokenizer.ggml.pre = lfm2``. llama.cpp reads that as a **Llama-3 style**
pre-tokenizer with ``ignore_merges`` on:

* the text is split with the Llama-3 regex,
* every piece is byte-encoded (GPT-2's ``bytes_to_unicode``),
* a piece that is itself a vocabulary entry becomes one token (the merges
  are not consulted), and a piece that is not falls back to the usual
  byte-level BPE;
* the special tokens in the text (``<|startoftext|>``, ``<|im_start|>``,
  ``<|im_end|>``) are cut out of the text before any of that and emitted
  as themselves.

The prompt the d1 template produces starts with ``<|startoftext|>``, so
the special-token handling is not optional here.

This is checked against llama.cpp's own ``/tokenize`` endpoint in
``scripts/check_tokenizer.py``; the two must agree token for token.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable

import regex

#: The Llama-3 pre-tokenizer regex, as llama.cpp spells it for
#: ``LLAMA_VOCAB_PRE_TYPE_LLAMA3``.
LLAMA3_REGEX = (
    r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])"
    r"|[^\r\n\p{L}\p{N}]?\p{L}+"
    r"|\p{N}{1,3}"
    r"| ?[^\s\p{L}\p{N}]+[\r\n]*"
    r"|\s*[\r\n]+"
    r"|\s+(?!\S)"
    r"|\s+"
)

#: GGUF token types that llama.cpp treats as special.
GGUF_TOKEN_TYPE_UNKNOWN = 2
GGUF_TOKEN_TYPE_CONTROL = 3
GGUF_TOKEN_TYPE_USER_DEFINED = 4


@lru_cache(maxsize=1)
def _byte_encoder() -> dict[int, str]:
    """GPT-2's ``bytes_to_unicode``: every byte gets one printable char."""
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("\xa1"), ord("\xac") + 1))
        + list(range(ord("\xae"), ord("\xff") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


@lru_cache(maxsize=1)
def _byte_encoder_table() -> dict[int, str]:
    return _byte_encoder()


class D1Tokenizer:
    """The d1 tokenizer."""

    def __init__(self, tokens: list[str], token_types: list[int], merges: list[str]) -> None:
        self.tokens = tokens
        self.token_types = token_types
        self.text_to_id: dict[str, int] = {}
        for i, t in enumerate(tokens):
            self.text_to_id.setdefault(t, i)
        self.byte_encoder = _byte_encoder()

        # merge ranks: "a b" -> rank
        self.merge_ranks: dict[tuple[str, str], int] = {}
        for i, m in enumerate(merges):
            parts = m.split(" ", 1)
            if len(parts) == 2:
                self.merge_ranks.setdefault((parts[0], parts[1]), i)

        # the special tokens, longest first so that a longer control token
        # wins over a shorter one that is a prefix of it
        special = [
            (i, t)
            for i, (t, ty) in enumerate(zip(tokens, token_types))
            if ty in (GGUF_TOKEN_TYPE_CONTROL, GGUF_TOKEN_TYPE_UNKNOWN, GGUF_TOKEN_TYPE_USER_DEFINED)
        ]
        special.sort(key=lambda it: (-len(it[1]), it[0]))
        self.special_tokens = special
        # one pattern for all of them, so the scan is done in C
        self._special_re = (
            re.compile("|".join(re.escape(t) for _, t in special if t)) if special else None
        )

    # -- construction --------------------------------------------------------

    @classmethod
    def from_gguf(cls, gguf) -> "D1Tokenizer":
        return cls(
            list(gguf.meta["tokenizer.ggml.tokens"]),
            list(gguf.meta["tokenizer.ggml.token_type"]),
            list(gguf.meta.get("tokenizer.ggml.merges", [])),
        )

    # -- the pieces ----------------------------------------------------------

    def _byte_encode(self, text: str) -> str:
        # str.translate runs the whole table in C, which matters when a
        # hundred prompts are tokenised at once
        return text.encode("utf-8").decode("latin-1").translate(_byte_encoder_table())

    def _split_special(self, text: str) -> list[tuple[str, str]]:
        """Cut the special tokens out of the text.

        Returns a list of ``("text", s)`` / ``("token", s)`` fragments.
        """
        if self._special_re is None:
            return [("text", text)]
        out: list[tuple[str, str]] = []
        pos = 0
        for m in self._special_re.finditer(text):
            if m.start() > pos:
                out.append(("text", text[pos : m.start()]))
            out.append(("token", m.group(0)))
            pos = m.end()
        if pos < len(text):
            out.append(("text", text[pos:]))
        return out

    def _bpe_piece(self, word: str) -> list[str]:
        """The BPE of one byte-encoded piece that is not in the vocabulary."""
        symbols = list(word)  # each byte-encoded char is one original byte
        if len(symbols) < 2:
            return symbols
        while True:
            best_rank = None
            best_i = -1
            for i in range(len(symbols) - 1):
                r = self.merge_ranks.get((symbols[i], symbols[i + 1]))
                if r is not None and (best_rank is None or r < best_rank):
                    best_rank = r
                    best_i = i
            if best_i < 0:
                break
            symbols[best_i : best_i + 2] = [symbols[best_i] + symbols[best_i + 1]]
        return symbols

    def _encode_text(self, text: str) -> list[int]:
        out: list[int] = []
        for piece in regex.findall(LLAMA3_REGEX, text):
            word = self._byte_encode(piece)
            tid = self.text_to_id.get(word)
            if tid is not None:
                out.append(tid)
                continue
            for sym in self._bpe_piece(word):
                tid = self.text_to_id.get(sym)
                if tid is None:
                    # a byte that is not in the vocabulary: fall back to the
                    # single-byte token, which llama.cpp also has
                    tid = self.text_to_id.get(self.byte_encoder[ord(sym) & 0xFF])
                if tid is None:
                    raise KeyError(f"token not in vocabulary: {sym!r}")
                out.append(tid)
        return out

    # -- the api -------------------------------------------------------------

    def encode(self, text: str, parse_special: bool = True) -> list[int]:
        """The token ids of ``text``."""
        ids: list[int] = []
        if not parse_special:
            return self._encode_text(text)
        for kind, frag in self._split_special(text):
            if kind == "token":
                tid = self.text_to_id.get(frag)
                if tid is None:
                    raise KeyError(f"special token not in vocabulary: {frag!r}")
                ids.append(tid)
            else:
                ids.extend(self._encode_text(frag))
        return ids

    def decode(self, ids: Iterable[int]) -> str:
        return "".join(self.tokens[i] for i in ids)

    def single_token(self, text: str) -> int | None:
        """The id of ``text`` if it is exactly one token."""
        return self.text_to_id.get(text)

    def single_token_any(self, forms: Iterable[str]) -> list[int]:
        """The ids of the forms that are a single token, in the given order."""
        out = []
        for form in forms:
            tid = self.text_to_id.get(form)
            if tid is not None:
                out.append(tid)
        return out
