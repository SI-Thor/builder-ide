# DESIGN — the why door: `POST /v1/why/digest`, `GET /v1/why/summary`

Status: **proposed** (2026-11-01, the ecology-thor seat, on
`research/ecology-bridge`). This is the door `world://why` needs —
asked for by the thor-world review of the why-stream draft: *"it must
read from a core door, not a side channel. If the door it needs
doesn't exist, propose it."* The door did not exist. This is it.

**Citation shorthand**

- **S** = `docs/design/core-spec.md` (v2) — §1.0 (the single writer),
  §1.8 (the closed event set), §4.2 (the JSON doors), §5.5 (the rails).
- **P** = `docs/design/core-doors.md` — the door precedents this
  proposal follows: the `/v1/world/scene` 501-with-the-seam-named
  answer for an unwired core, the per-agent token's `agent` claim, the
  recipe read door's shape.
- **E** = SI-Thor/ecology-thor — the publisher this door serves, and
  its frozen JSON contract (`docs/INTEGRATION.md` there).

---

## 0. The problem, in one paragraph

The ecology (the attention auction and WHY ledger that prices the
box's work) runs as its own process — by §1.0's rule it must never be
a second writer. It has a summary to publish (a per-tick digest:
purposes alive/unknown/dead, admissions and vetoes, spend in the
night's own units, a chain hash over every decision), and thor-world
wants to serve it as `world://why`. Without a door, the only paths are
side channels (world-mcp reading the ecology's own files) that the
audit log cannot see — exactly what the purity law exists to prevent.
So the door takes the shape every other external fact takes: **the
publisher writes through a door, the core's single writer records it
as an event, and every reader reads the fold.**

## 1. The shape

| door | verb | who | what |
|---|---|---|---|
| `/v1/why/digest` | POST | the ecology's token (a per-agent token, `agent: "ecology"`) | publish one digest — one `why.digest` audit event |
| `/v1/why/summary` | GET | any class that reads the slate | the latest digest, folded from the log |

No new stream door: `GET /v1/events?types=why.digest` (§4.3, the
existing SSE fanout) already is the live stream — thor-world's
`watch_events` rides it unchanged.

### 1.1 The publisher door (`POST /v1/why/digest`)

- **Auth**: a per-agent token (core-doors §2) — the `agent` claim
  `"ecology"` rides every audit row, so the log answers "who published
  this digest" from the row alone.
- **Payload**: the ecology's frozen JSON contract verbatim (E
  `docs/INTEGRATION.md`: `tick`, state counts, last auction's
  admissions/vetoes, `spent_*` in gpu-seconds/joules/cents, cascade
  and overrun counters, `safe_mode`, `conservation_ok`, `chain_hash`,
  events hashed/dropped). The contract is **append-only**; the core
  stores it as-is (a 4 KiB cap like every payload — §1.8 — and the
  digest is well under it; a digest that does not fit is refused, not
  truncated).
- **Rate shape**: the ecology publishes **on change at most once a
  second** (its tick is 100 Hz; the digest cadence is a decimation the
  publisher owns). A core under load may refuse with 429; the
  publisher backs off and retries on the next change — a dropped
  digest is one stale tick, not a gap in history that matters.
- **Idempotency**: `Idempotency-Key` required (the standard door rule);
  the key is the digest's `(tick, chain_hash)` pair, so a retry after
  a dropped connection is answered from the first write.

### 1.2 The event (the closed set grows by one)

`why.digest` — payload: the digest JSON + the publisher's tick.
Mirrored into `core/records.py`, `core/night/events.py` and
`core/recipe/events.py` the way the tiles' four event types were
(tiles §"how it connects"): one schema change, every reader of the log
agrees. The event is written by the core's single writer (§1.0) — the
ecology never touches the ledger.

### 1.3 The read door (`GET /v1/why/summary`)

- Returns `{digest: <latest why.digest payload>, seq: <its event's
  seq>, at: <its timestamp>}` — the fold, newest wins, nothing derived.
- **Unwired core answers 501 with the seam named** (the
  `/v1/world/scene` precedent, P): `{"error": {"code": "not_wired",
  "message": "the why door is proposed but not wired; the seam is
  core/night/why.py:fold_latest_digest"}}`. A client (thor-world's
  `world://why`) surfaces that honestly instead of pretending — which
  is exactly what its draft round now does.

## 2. What this deliberately is not

- **Not a second writer.** The ecology POSTs like any agent; the core
  writes the row. If the ecology dies, its digest goes stale and the
  fold says so by timestamp — the ledger stays the only truth.
- **Not a control channel.** The door publishes facts. Nothing on the
  core side *acts* on a digest (the auction's decisions remain the
  ecology's own, and the night runner stays the runner); when the
  exchange proposal is ever adopted, that is a separate door with its
  own review.
- **Not a firehose.** One event per changed second at most; the
  backlog cost of a night is ~40k rows at 1 Hz worst case, a fraction
  of one night's `day.change` traffic — and the publisher owns the
  decimation, so it can run quieter (on-change, or once a minute)
  without the door changing.

## 3. The acceptance test (what landing means)

1. `POST /v1/why/digest` with a valid contract → one `why.digest` row
   with the `agent: "ecology"` claim; a replay with the same
   Idempotency-Key → the same row, no second write.
2. A digest with a field missing from the frozen contract → refused
   at the door (the contract's own parser is the validator, shared
   with thor-world's — one definition, E's test file).
3. `GET /v1/why/summary` → the posted digest with its seq; on an
   unwired core → the 501 with the seam named.
4. `GET /v1/events?types=why.digest` → the stream a subscriber can
   resume by cursor (no new machinery — the assertion is that the
   existing fanout carries the new type).
5. thor-world's `world://why` (its `research/ecology-why-door` branch)
   reads the summary door end to end against a wired core, and shows
   the 501 notice against an unwired one.

## 4. Open questions for the review

1. **The publisher token's class.** The ecology is not a character, a
   builder or the panel; it is infrastructure. A dedicated token class
   (`service`) with the `agent` claim, or an existing class with the
   claim alone? core-doors §2 says "recorded, never gated" — the
   claim approach needs no new gating either way.
2. **Retention.** Does `why.digest` ride the same retention as
   telemetry-ish events, or is a night of digests worth compacting
   (e.g. keep the last digest per minute past 24 h)? The tiles' play
   records kept everything; a 1 Hz digest stream may not need to.
3. **The joules axis.** The digest's `spent_joules` is the ecology's
   rail accounting (admission envelopes); the night's `Rail` is
   gpu-minutes/cents/wall-minutes. The fold carries both spellings
   side by side for now — should the door normalize to the night's
   units, or is carrying the publisher's own units the more honest
   record? (The bridge module's rebase made the auction bid in the
   night's units; the digest is the publisher's own book, which argues
   for carrying it as-published with the units named.)
