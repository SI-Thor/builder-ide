"""builder-ide core service — half A (core-spec v2).

Owns the SQLite audit ledger (the source of truth), the projections rebuilt
by folding it, the FastAPI service with the spec's §4.2 endpoints, and the
SSE event stream. Work orders are the worked example of an entity whose
whole lifecycle is persisted through the ledger.
"""

__version__ = "0.1.0"
