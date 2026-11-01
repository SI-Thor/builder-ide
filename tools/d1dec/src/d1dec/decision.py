"""The decision head: from logits to calibrated probabilities.

The d1 models answer with the probability of each option, at the model's
own temperature. The temperature comes out of the GGUF
(``lfm3.decision.temperature.<type>``), and llama.cpp's
``format_answer`` does:

* the logit of an option is the **largest** logit over the option's label
  group (a label may be more than one token — "A" and " A");
* the probabilities are a softmax over those logits at the temperature.

The answer of a question is then:

* ``choice`` — the option with the largest probability;
* ``score``  — the **median** level: the first whose cumulative probability
  reaches one half;
* ``noul``   — the probability of the "true" option.

The confidence of a d1 answer is the probability of the answer itself.
"""

from __future__ import annotations

import math
from typing import Any

import torch


def label_scores(logits: torch.Tensor, groups: list[list[int]]) -> list[float]:
    """The logit of every option: the largest logit of its label group."""
    return [max(float(logits[t]) for t in group) for group in groups]


def softmax_at_temperature(scores: list[float], temperature: float) -> list[float]:
    """The calibrated probabilities of the options."""
    if not scores:
        return []
    m = max(scores)
    exps = [math.exp((s - m) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def decision_probabilities(
    logits: torch.Tensor,
    groups: list[list[int]],
    temperature: float,
) -> list[float]:
    """The calibrated probabilities of one question."""
    return softmax_at_temperature(label_scores(logits, groups), temperature)


def format_answer(
    question: Any,
    probs: list[float],
) -> dict[str, Any]:
    """The answer of one question, in llama.cpp's shape."""
    options = question.options
    n = len(options)
    if question.type == "noul":
        for i, opt in enumerate(options):
            if opt.key == "true":
                return {"type": "noul", "noul": probs[i]}
        return {"type": "noul", "noul": 0.0}

    probabilities = {options[i].key: probs[i] for i in range(n)}
    confidence = max(probs) if probs else 0.0
    if question.type == "choice":
        best = max(range(n), key=lambda i: probs[i])
        return {
            "type": "choice",
            "choice": options[best].key,
            "probabilities": probabilities,
            "confidence": confidence,
        }

    # the median level: the first whose cumulative probability reaches one half
    mass = 0.0
    level = n - 1
    for i in range(n):
        mass += probs[i]
        level = i
        if mass >= 0.5:
            break
    legend = {options[i].key: options[i].description for i in range(n)}
    return {
        "type": "score",
        "score": float(level),
        "legend": legend,
        "probabilities": probabilities,
        "confidence": confidence,
    }
