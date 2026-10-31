"""Import alias so the vendored golden-corpus test runs VERBATIM.

tests/test_why_corpus.py is copied byte-identical from cognitive-ecology,
where the kernel lives at ``ecology.why``. Here it is vendored at
``core.why`` (core/why/VENDORED.md). Rather than editing the test — which
would break the "unchanged" property that pins us to upstream semantics —
this conftest binds ``ecology.why`` to the vendored package before the
test module imports it.
"""

from __future__ import annotations

import sys
import types

from core import why as _vendored_why

_ecology = sys.modules.get("ecology")
if _ecology is None:
    _ecology = types.ModuleType("ecology")
    _ecology.__path__ = []  # mark as package so submodule imports resolve
    sys.modules["ecology"] = _ecology
_ecology.why = _vendored_why
sys.modules.setdefault("ecology.why", _vendored_why)
