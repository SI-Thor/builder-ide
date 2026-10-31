"""Typed edits: applying op lists to a recipe document, and diffing two of them.

A recipe never mutates in place; change is an **edit**: a list of typed
operations against a parent version (§1.1). The diff *is* the op list in
canonical JSON.

Path grammar
------------
An op path is dotted. The first segment decides the world it lives in:

* a reserved document key (``id``, ``name``, ``schema_version``,
  ``engine_pin``, ``seeds``, ``entries``, ``constraints``) → the path is
  document-relative;
* anything else → the path is entry-relative. The longest prefix that names
  an existing entry is the entry path, the rest addresses inside it. The
  spec's own example is ``harbor.crates.params.count``.

``entries.<entry path>`` is accepted as an alias for a whole-entry path, so an
entry can be added, replaced or removed.

Op verbs
--------
``set``    replace the value at the path (a missing final key in a mapping is
           created — whether it is *allowed* is the vocabulary schema's call);
``add``    append to the list at the path, or create a new entry at an entry
           path that does not exist yet;
``remove`` delete the key at the path, or the item at a list index.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from core.recipe.errors import EditRejected
from core.recipe.models import Op, Recipe

__all__ = [
    "apply_ops",
    "diff_recipes",
    "touched_entries",
    "ops_by_entry",
    "DOCUMENT_KEYS",
    "MAX_ENTRY_SEGMENTS",
]

DOCUMENT_KEYS = frozenset(
    {"id", "name", "schema_version", "engine_pin", "seeds", "entries", "constraints"}
)
MAX_ENTRY_SEGMENTS = 3


def _split(path: str) -> list[str]:
    segments = path.split(".")
    if not path or any(not segment for segment in segments):
        raise EditRejected(f"malformed op path: {path!r}")
    return segments


def _looks_like_entry_path(segments: list[str]) -> bool:
    return 1 <= len(segments) <= MAX_ENTRY_SEGMENTS


def _entry_prefix(entries: dict[str, Any], segments: list[str]) -> tuple[str | None, list[str]]:
    """The longest prefix of ``segments`` naming an entry, and the remainder."""
    for size in range(len(segments), 0, -1):
        candidate = ".".join(segments[:size])
        if candidate in entries:
            return candidate, segments[size:]
    return None, segments


def _descend(container: Any, segments: list[str], path: str) -> tuple[Any, Any]:
    """Walk to the parent of the last segment. Returns (parent, last key)."""
    current = container
    for segment in segments[:-1]:
        if isinstance(current, list):
            if not segment.isdigit():
                raise EditRejected(f"no such path: {path!r}")
            position = int(segment)
            if position >= len(current):
                raise EditRejected(f"no such path: {path!r}")
            current = current[position]
            continue
        if not isinstance(current, dict):
            raise EditRejected(f"no such path: {path!r}")
        if segment not in current:
            raise EditRejected(f"no such path: {path!r}")
        current = current[segment]
    last = segments[-1]
    if isinstance(current, list):
        if not last.isdigit():
            raise EditRejected(f"no such path: {path!r}")
        position = int(last)
        if position >= len(current):
            raise EditRejected(f"no such path: {path!r}")
        return current, position
    if not isinstance(current, dict):
        raise EditRejected(f"no such path: {path!r}")
    return current, last


def _locate(document: dict[str, Any], path: str, creating: bool = False) -> tuple[Any, Any]:
    """Find the container and key an op addresses.

    ``creating`` allows a path that names no existing entry to address a new
    entry — only ``add`` may do that.
    """
    segments = _split(path)
    entries = document.get("entries", {})

    if segments[0] == "entries":
        rest = segments[1:]
        if not rest:
            raise EditRejected(f"malformed op path: {path!r}")
        entry_path, remainder = _entry_prefix(entries, rest)
        if entry_path is None:
            if not creating or not _looks_like_entry_path(rest):
                raise EditRejected(f"no such entry: {'.'.join(rest)!r}")
            return entries, ".".join(rest)
        if not remainder:
            return entries, entry_path
        return _descend(entries[entry_path], remainder, path)

    if segments[0] in DOCUMENT_KEYS:
        if len(segments) == 1:
            return document, segments[0]
        return _descend(document, segments, path)

    entry_path, remainder = _entry_prefix(entries, segments)
    if entry_path is None:
        if creating and _looks_like_entry_path(segments):
            return entries, ".".join(segments)
        raise EditRejected(f"no such entry: {segments[0]!r}")
    if not remainder:
        return entries, entry_path
    return _descend(entries[entry_path], remainder, path)


def _apply_one(document: dict[str, Any], op: Op) -> None:
    if op.op == "add":
        container, key = _locate(document, op.path, creating=True)
        if isinstance(container, dict):
            if key not in container:
                container[key] = deepcopy(op.value)
                return
            existing = container[key]
            if isinstance(existing, list):
                existing.append(deepcopy(op.value))
                return
            raise EditRejected(f"cannot add {op.path!r}: it is not a list")
        raise EditRejected(f"cannot add {op.path!r}")

    container, key = _locate(document, op.path)

    if op.op == "set":
        if isinstance(container, list):
            container[key] = deepcopy(op.value)
            return
        if not isinstance(container, dict):
            raise EditRejected(f"no such path: {op.path!r}")
        container[key] = deepcopy(op.value)
        return

    if op.op == "remove":
        if isinstance(container, list):
            del container[key]
            return
        if not isinstance(container, dict):
            raise EditRejected(f"no such path: {op.path!r}")
        if key not in container:
            raise EditRejected(f"cannot remove {op.path!r}: it does not exist")
        del container[key]
        return

    raise EditRejected(f"unknown op: {op.op!r}")


def apply_ops(recipe: Recipe, ops: list[Op]) -> Recipe:
    """Apply ops to a copy of the recipe. The base is never mutated."""
    document = recipe.model_dump()
    for op in ops:
        _apply_one(document, op)
    return Recipe.model_validate(document)


def _entry_path_of(document: dict[str, Any], path: str) -> str | None:
    """The entry an op path touches, if any."""
    segments = _split(path)
    entries = document.get("entries", {})
    if segments[0] == "entries":
        rest = segments[1:]
        entry_path, _ = _entry_prefix(entries, rest)
        return entry_path
    if segments[0] in DOCUMENT_KEYS:
        return None
    entry_path, _ = _entry_prefix(entries, segments)
    return entry_path


def touched_entries(recipe: Recipe, ops: list[Op]) -> set[str]:
    """The entries an edit reaches — the first term of the dirty set (§1.1)."""
    document = recipe.model_dump()
    touched: set[str] = set()
    for op in ops:
        path = _entry_path_of(document, op.path)
        if path:
            touched.add(path)
    return touched


def ops_by_entry(recipe: Recipe, ops: list[Op]) -> dict[str, list[Op]]:
    """An op list grouped by the entry each op is addressed inside.

    The regenerator's slicing: a per-entry stage re-executes under *its*
    ops, not the whole diff. Ops outside any entry (document-relative keys
    like ``seeds`` or ``engine_pin``) are not in any group — their effect
    reaches entries through the effective-key rule, not through op shape
    (``core/engine/DIRTY.md`` §1)."""
    document = recipe.model_dump()
    grouped: dict[str, list[Op]] = {}
    for op in ops:
        path = _entry_path_of(document, op.path)
        if path:
            grouped.setdefault(path, []).append(op)
    return grouped


def _diff_mapping(base: dict[str, Any], head: dict[str, Any], prefix: str) -> list[Op]:
    ops: list[Op] = []
    for key in sorted(set(base) | set(head)):
        path = f"{prefix}.{key}" if prefix else key
        in_base = key in base
        in_head = key in head
        if in_base and not in_head:
            ops.append(Op(op="remove", path=path))
        elif in_head and not in_base:
            ops.append(Op(op="set", path=path, value=deepcopy(head[key])))
        elif base[key] != head[key]:
            ops.append(Op(op="set", path=path, value=deepcopy(head[key])))
    return ops


def _diff_entry(base: dict[str, Any], head: dict[str, Any], path: str) -> list[Op]:
    ops: list[Op] = []
    for field in ("kind", "seed", "origin"):
        if base.get(field) != head.get(field):
            ops.append(Op(op="set", path=f"{path}.{field}", value=head.get(field)))
    if base.get("generator") != head.get("generator"):
        ops.append(
            Op(op="set", path=f"{path}.generator", value=deepcopy(head.get("generator")))
        )
    ops.extend(_diff_mapping(base.get("params", {}), head.get("params", {}), f"{path}.params"))
    if base.get("constraints") != head.get("constraints"):
        ops.append(Op(op="set", path=f"{path}.constraints", value=deepcopy(head.get("constraints"))))
    if base.get("assets") != head.get("assets"):
        ops.append(Op(op="set", path=f"{path}.assets", value=deepcopy(head.get("assets"))))
    return ops


def diff_recipes(base: Recipe, head: Recipe) -> list[Op]:
    """The canonical op list that turns ``base`` into ``head``."""
    base_doc = base.model_dump()
    head_doc = head.model_dump()
    ops: list[Op] = []

    for field in ("name", "schema_version"):
        if base_doc.get(field) != head_doc.get(field):
            ops.append(Op(op="set", path=field, value=head_doc.get(field)))

    base_pin = base_doc.get("engine_pin", {})
    head_pin = head_doc.get("engine_pin", {})
    ops.extend(_diff_mapping(base_pin, head_pin, "engine_pin"))

    ops.extend(_diff_mapping(base_doc.get("seeds", {}), head_doc.get("seeds", {}), "seeds"))

    if base_doc.get("constraints") != head_doc.get("constraints"):
        ops.append(Op(op="set", path="constraints", value=deepcopy(head_doc.get("constraints"))))

    base_entries = base_doc.get("entries", {})
    head_entries = head_doc.get("entries", {})
    for path in sorted(set(base_entries) | set(head_entries)):
        if path not in head_entries:
            ops.append(Op(op="remove", path=path))
        elif path not in base_entries:
            ops.append(Op(op="add", path=path, value=deepcopy(head_entries[path])))
        else:
            ops.extend(_diff_entry(base_entries[path], head_entries[path], path))

    return ops
