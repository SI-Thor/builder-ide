"""builder-ide core service (core-spec v2).

One tree, seven seats. The packages here follow the seat split of the core
spec (docs/design/core-spec.md), and every seat's package is a real
implementation — no stubs remain:

- ``core.api``, ``core.svc``, ``core.models``, ``core.events``,
  ``core.fold``, ``core.store`` — the audit ledger, the fold that rebuilds
  every projection from it, the FastAPI service and the work-order
  lifecycle (the ``core-api`` seat).
- ``core.recipe`` — the recipe store: recipes, versions,
  branches, typed edits, the recipe hash, the node registry and the stage
  cache (the ``core-recipe`` seat).
- ``core.vocab`` — the closed vocabulary, the call door, sealed
  predictions, the gate and the Prop-maker (the ``vocab`` seat).
- ``core.night`` — the night, the iterator loop and the morning report
  (the ``night-runner`` seat).
- ``core.coldstart`` — ask-mode, the melt and the calibration batch
  (the ``cold-start`` seat).
- ``core.why``, ``core.justification`` — the vendored WHY kernel and the
  justification service that attaches it to the spec's records
  (the ``why-kernel`` seat).
- ``builder_usd`` (under ``core/usd/src``) — the compiled-scene backbone:
  recipe to USD, STEP to GLB (the ``usd-backbone`` seat).

The seat packages are disjoint subpackages of ``core`` and share the
ledger's records and hashing helpers rather than redeclaring them; see
INTEGRATION.md for how the duplicated models were reconciled.
"""

__version__ = "0.1.0"
