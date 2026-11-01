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

- **Auth**: a per-agent token (core-doors §2) of class `seat` —
  `{"class": "seat", "actor": "ecology", "agent": "ecology"}` (§4.1
  answers why an existing class, not a new `service` one) — the
  `agent` claim `"ecology"` rides every audit row, so the log answers
  "who published this digest" from the row alone.
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

## 4. The three questions, answered

Posed as open in the first draft; each now has a proposed answer,
grounded in what the core's code actually does. Still the review's
call — these are arguments, not landings.

### 4.1 The publisher token's class — `seat`, not a new `service`

A new `service` class is the wrong move for a reason `check_class`
makes mechanical: a class no door names can call nothing, so a new
class means editing every door's allowed set — new gating, which is
exactly what core-doors §2's "recorded, never gated" exists to avoid.
The registry already has the shape for infrastructure: `seat` sits in
`TOKEN_CLASSES` (`core/auth.py`) used by no door yet, and the
per-agent precedent (world-mcp's own token) is an existing class plus
the `agent` claim. So the publisher's entry:

```json
{"class": "seat", "actor": "ecology", "agent": "ecology"}
```

The door's allowed set is `{owner, seat}` — `seat` for the daemon,
`owner` for dev and tests, the same asymmetry every door has. The
audit row answers "who published this" from itself:
`{kind: why.digest, via: seat:ecology, agent: ecology}`.

### 4.2 Retention — keep everything; the publisher owns the rate

The store has no retention machinery at all — the only DELETE in
`core/store.py` is idempotency-key cleanup — so "ride the same
retention as telemetry" *is* "keep everything", and compaction would
be new machinery whose first customer is a stream measured smaller
than one night's `day.change` traffic (~40k rows at 1 Hz worst case,
a few hundred bytes each). Two reasons not to compact anyway:

1. **The replay depends on completeness.** The mini-night-2 replay
   had to *reconstruct* its ledger because the runner logged only
   what ran; the study's tiles-rule-8 critique says the same about
   bid sets. The digests are the auction's own per-tick record —
   exactly the off-policy evidence any future exchange door will be
   argued from. Compacting them spends that evidence to save
   megabytes.
2. **Volume has a valve upstream.** The publisher owns the
   decimation (on-change, or once a minute — §1.1); if a night's
   ledger ever says the stream is too big, the cadence changes at
   the source, where it is one number, not a retention policy at
   the record.

Revisit only when a real night's ledger says so — the same
discipline the peak history takes.

### 4.3 The joules axis — carry as-published, name the units

The door stores the digest verbatim (the frozen contract, E
`docs/INTEGRATION.md`); the summary returns it verbatim; **no
conversion at the door.** Three reasons:

1. **A door that converts units is a second place accounting
   arithmetic lives.** The single-writer rule (S §1.0) keeps the
   books in one place; unit conversion at the door is where silent
   errors breed — the 11.76-min bar was a units/pricing confusion,
   and it survived review precisely because two spellings of the
   same quantity were in the room.
2. **The two books measure different things.** The ecology's rails
   are *admission envelopes* (float, "not accounting truth" — the
   bridge's own README); the night's `Rail` is the ledger's booked
   cost. Normalizing at the door would make a stale envelope
   indistinguishable from a booked minute.
3. **Comparability already has its home.** The bridge converts at
   the edge where it is tested (bids speak `core.records.Rail`'s
   axes, unconverted); a fold that wants gpu-minutes divides by 60
   at read time, where a test can see it.

Concretely: the digest keeps `spent_gpu_seconds` / `spent_joules` /
`spent_cents` as published, and the frozen contract's next
append-only version carries a one-time
`"units": {"gpu": "s", "energy": "J", "money": "cents"}` block, so
the row is self-describing without any conversion.

*(Cross-reference: the chained journal these digests' `chain_hash`
aligns with has now landed on thor-admit's side as
`research/ecology-ledger` — the audit log and the daemon's log can
be verified against each other, which is the retention answer's
other half: what is kept can also be proved whole.)*
