"""The closed, typed vocabulary (§1.5): characters change the world only
through words, and anything outside the param schema is refused at the
door — that refusal, audited, is the "I can't do rope yet" moment.

The param schema subset is validated in code, not by a prompt: integer /
number with required minimum+maximum, string only as enum, boolean,
integer seed; ≤ 8 properties; additionalProperties false; nesting ≤ 2;
canonical params ≤ 512 bytes. A character can never smuggle free text.

Committing the resulting RecipeEdit is the recipe half's seam: the call
returns the validated edit and, when that half is present, commits it.
"""
from __future__ import annotations

from ..canon import canonical_bytes, new_id
from ..errors import NotFound, Refused
from ..events import character_actor
from ..models import Op, RecipeEdit, VocabularyEntry

MAX_PROPERTIES = 8
MAX_PARAMS_BYTES = 512
ALLOWED_TYPES = {"integer", "number", "string", "boolean", "seed"}


def validate_schema_subset(schema: dict) -> None:
    """Reject schemas outside the bounded subset — a word is always
    validatable and diffable (§1.5)."""
    if schema.get("type") != "object":
        raise Refused("params schema must be type object")
    props = schema.get("properties", {})
    if len(props) > MAX_PROPERTIES:
        raise Refused(f"≤ {MAX_PROPERTIES} properties per word")
    if schema.get("additionalProperties", True) is not False:
        raise Refused("additionalProperties: false is required — no free text can be smuggled")
    for name, spec in props.items():
        t = spec.get("type")
        if t not in ALLOWED_TYPES:
            raise Refused(f"property {name!r}: type must be one of {sorted(ALLOWED_TYPES)}")
        if t in ("integer", "number") and ("minimum" not in spec or "maximum" not in spec):
            raise Refused(f"property {name!r}: integer/number require minimum and maximum")
        if t == "string" and "enum" not in spec:
            raise Refused(f"property {name!r}: string is allowed only as enum")


def validate_params(schema: dict, params: dict) -> None:
    """Validate a call's params against the word's schema; anything outside
    is refused at the door (the edges are the story)."""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    given = set(params)
    extra = given - set(props)
    if extra:
        raise Refused(
            f"params outside the word's schema are refused at the door: {sorted(extra)}",
            word_schema=sorted(props))
    missing = required - given
    if missing:
        raise Refused(f"missing required params: {sorted(missing)}")
    for name, value in params.items():
        spec = dict(props.get(name, {}))
        if spec.get("type") == "seed":
            spec["type"] = "integer"
        t = spec.get("type")
        if t == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise Refused(f"param {name} must be an integer")
        if t == "number" and not isinstance(value, (int, float)):
            raise Refused(f"param {name} must be a number")
        if t == "boolean" and not isinstance(value, bool):
            raise Refused(f"param {name} must be a boolean")
        if t == "string" and (not isinstance(value, str) or value not in spec.get("enum", [])):
            raise Refused(
                f"param {name} must be one of the enum {spec.get('enum')} — free text "
                "is never accepted")
        if t in ("integer", "number"):
            lo, hi = spec.get("minimum"), spec.get("maximum")
            if lo is not None and value < lo:
                raise Refused(f"param {name} below minimum {lo} (got {value})")
            if hi is not None and value > hi:
                raise Refused(f"param {name} above maximum {hi} (got {value})")
    if len(canonical_bytes(params)) > MAX_PARAMS_BYTES:
        raise Refused(f"canonical params exceed {MAX_PARAMS_BYTES} bytes")


class VocabService:
    def __init__(self, core) -> None:
        self.core = core
        self.store = core.store

    def add_word(self, entry: dict, actor) -> VocabularyEntry:
        word = entry.get("word", "")
        # Provenance is written by the core, not by whoever is posting: a
        # word filed without an origin gets the door's own (§1.5 — the same
        # "builtin" the seeded words carry; promotion stamps the wo_ id).
        entry.setdefault("provenance", {"origin": "builtin"})
        try:
            v = VocabularyEntry(**entry)
        except Exception as e:
            raise Refused(f"vocabulary entry not schema-valid: {e}") from e
        validate_schema_subset(v.params)
        ev = self.store.new_event(
            "vocab.word.added", actor, {"entity_kind": "vocab_word", "entity_id": word},
            {"word": word, "status": v.status, "entry": v.model_dump(mode="json")},
        )
        self.store.append(ev)
        return self.get(word)

    def set_status(self, word: str, status: str, actor) -> VocabularyEntry:
        if status not in ("active", "coming-soon", "retired"):
            raise Refused("status must be active|coming-soon|retired")
        ev = self.store.new_event(
            "vocab.word.status", actor, {"entity_kind": "vocab_word", "entity_id": word},
            {"status": status},
        )
        self.store.append(ev)
        return self.get(word)

    def get(self, word: str) -> VocabularyEntry:
        row = self.store.get_row("vocab_words", {"word": word})
        if row is None:
            raise NotFound(f"vocabulary word {word!r} not found — "
                           "the refusal is the “I can't do that yet” moment", word=word)
        return VocabularyEntry(**row["payload"])

    def list(self) -> list[VocabularyEntry]:
        return [VocabularyEntry(**r["payload"]) for r in self.store.scan("vocab_words")]

    def call(self, character_id: str, word: str, params: dict,
             node: str | None = None, region: str | None = None,
             *, idem_key: str | None = None,
             agent: str | None = None) -> dict:
        """POST /v1/vocab/call {word, node|region, params} → a validated
        RecipeEdit authored {kind: character, via: word}. Refusals are
        audited (vocab.call with refused=true). ``agent`` is the per-agent
        token's claim, recorded on the row and gating nothing."""
        actor = character_actor(character_id, via=word, agent=agent)
        try:
            entry = self.get(word)
        except NotFound:
            ev = self.store.new_event(
                "vocab.call", actor, {"entity_kind": "vocab_word", "entity_id": word},
                {"word": word, "params": params, "refusal_reason": "unknown word"})
            self.store.append_refused(ev)
            raise
        refusal = None
        if entry.status != "active":
            refusal = f"word is {entry.status}, not active — the limit, said aloud"
        elif entry.owner_character and entry.owner_character != character_id:
            refusal = f"word belongs to {entry.owner_character}, not {character_id}"
        else:
            try:
                validate_params(entry.params, params)
            except Refused as r:
                refusal = str(r.message if hasattr(r, "message") else r)
            else:
                # the target must exist: a node id or a region, resolved
                # through the registry when given (the recipe half keeps it
                # current). Once the registry has been published, a call may
                # not name a node that is not in it.
                if node:
                    refs = self.store.scan("node_refs")
                    known = {r.get("node_id") for r in refs if not r.get("orphaned")}
                    if refs and node not in known:
                        refusal = f"node {node!r} is not in the node registry"
        if refusal is not None:
            ev = self.store.new_event(
                "vocab.call", actor, {"entity_kind": "vocab_word", "entity_id": word},
                {"word": word, "params": params, "refusal_reason": refusal})
            self.store.append_refused(ev)
            raise Refused(refusal, word=word)
        # the target must exist: a node id or a region, resolved through the
        # registry when given (the recipe half keeps it current)
        target = node or region
        edit = RecipeEdit(
            id=new_id("edit"), base="head", ops=[
                Op(op="set", path=f"{target or 'scene'}.params", value=params)
            ] if target else [Op(op="set", path="params", value=params)],
            author=character_actor(character_id, via=word, agent=agent),
            message=f"{word} → {target}"[:80],
        )
        ev = self.store.new_event(
            "vocab.call", actor, {"entity_kind": "vocab_word", "entity_id": word},
            {"word": word, "params": params, "node": node, "region": region,
             "edit": edit.model_dump(mode="json")})
        _, resp = self.store.append(
            ev, idem_key=idem_key,
            response_builder=lambda e: {"word": word, "edit": edit.model_dump(mode="json"),
                                        "committed": False})
        if resp and resp.get("__replay__"):
            return resp["body"]
        committed, ver = False, None
        try:
            ver = self.core.recipes.commit_edit(edit)
            committed = True
        except Exception:
            pass  # the recipe half is not merged; the edit stays a proposal
        return {"word": word, "edit": edit.model_dump(mode="json"),
                "committed": committed, "version": ver}
