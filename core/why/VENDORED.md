# VENDORED — the WHY justification kernel

## Upstream

- Repository: `github.com/SuperInstance/cognitive-ecology` (MIT; our crew's
  project — `LICENSE` here is the upstream licence file, verbatim)
- Commit: `a0fb2102f1c360be00955daf1397c47b746c6707` ("docs: changelog for
  v0.1.0", 2026-10-31)
- Vendored: 2026-10-30, on branch `why-kernel`, per BRIEF.md and the
  cognitive-ecology fit study (`docs/research/cogeco.md` — file not present in
  this worktree at vendoring time; the brief carries its recommendation:
  vendor the WHY kernel now, borrow lifecycle and consolidation as behaviours,
  do not adopt the tick loop or attention economy).

## What was copied

| There (cognitive-ecology) | Here | Fidelity |
|---|---|---|
| `src/ecology/why/__init__.py` | `core/why/__init__.py` | byte-identical |
| `src/ecology/why/model.py` | `core/why/model.py` | byte-identical |
| `src/ecology/why/parse.py` | `core/why/parse.py` | byte-identical |
| `src/ecology/why/reach.py` | `core/why/reach.py` | byte-identical |
| `src/ecology/why/dominators.py` | `core/why/dominators.py` | byte-identical |
| `src/ecology/why/dates.py` | `core/why/dates.py` | byte-identical |
| `tests/test_why_corpus.py` | `tests/test_why_corpus.py` | byte-identical |
| `tests/corpus/**` (15 golden pairs + 6 stray root-level files) | `tests/corpus/**` | byte-identical |

sha256 of the vendored modules at copy time:

```
6e3f028d…  core/why/dates.py
4dce4e44…  core/why/dominators.py
6f711869…  core/why/__init__.py
d1bd0fc5…  core/why/model.py
d8e89fab…  core/why/parse.py
47b9fff9…  core/why/reach.py
d138c765…  tests/test_why_corpus.py
```

## Changes

**None to the kernel.** The only additions around it:

- `tests/conftest.py` binds the module name `ecology.why` to `core.why`, so
  the golden-corpus test runs here **verbatim** (its `from ecology.why
  import …` lines resolve to this vendored package). The test file itself is
  untouched.
- ADR-0002 (`docs/ADRs/0002-questionable-vs-dead.md` upstream) is the
  semantics this vendoring carries into builder-ide: root *attested dead* →
  explicit dependents dead (removal justified); root liveness *unknown*
  (attestation withdrawn, review-by stale past grace, inferred-only path) →
  dependents **questionable**, never deleted. The attachment layer
  (`core.justification`) relies on exactly those two strengths.

## Upstream sync

`diff -r <clone>/src/ecology/why core/why` (and the same for
`tests/corpus`, `tests/test_why_corpus.py`) is the whole upgrade procedure;
any diff is a semantic decision, not a refactor (upstream's own rule, quoted
in its corpus test). Notes to send back upstream are collected in this
branch's final report.
