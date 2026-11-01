"""Try one prop in one kernel, to see what the model gives back."""

from __future__ import annotations

import sys

from core.cadbakeoff.model import CloudModel, count_tokens, extract_json, extract_python
from core.cadbakeoff.prompts import build_prompt

prop = sys.argv[1] if len(sys.argv) > 1 else "crate"
kernel = sys.argv[2] if len(sys.argv) > 2 else "solidcraft"

model = CloudModel()
prompt = build_prompt(prop, kernel)
reply = model.call(prompt)
print("model:", reply.model, "out_tokens:", reply.output_tokens, "in_tokens:", reply.input_tokens,
      "ms:", reply.duration_ms)
print("=" * 70)
print(reply.text[:4000])
print("=" * 70)
if kernel == "solidcraft":
    payload, err = extract_json(reply.text)
    print("extract_json error:", err)
    if payload:
        print("script tokens:", count_tokens(payload))
        print(payload[:3000])
else:
    payload, err = extract_python(reply.text)
    print("extract_python error:", err)
    if payload:
        print("script tokens:", count_tokens(payload))
        print(payload[:3000])
