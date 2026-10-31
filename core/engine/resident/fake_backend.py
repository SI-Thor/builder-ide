"""The deterministic fake scene — what the resident process runs when no real
engine is behind it.

It is a scene in name and structure only: a list of objects, one per unit of
each recipe entry, and a material per entry. What it is *for* is the
machinery around it — the RPC, the health checks, the restart policy, the
checkpoint cadence, the memory guard and the crash recovery — all of which
need a resident that behaves like a resident without needing a GPU.

It has the properties the tests depend on:

* **deterministic** — the same document gives the same objects, the same
  state and the same bytes, so a digest is a promise;
* **sensitive** — changing a parameter changes the objects, so a digest
  actually distinguishes two states;
* **in place** — a changed entry's objects are rebuilt and the untouched
  entries' objects are left exactly as they were, so the resident's
  behaviour matches the claim.

Standalone by design: no ``core`` import, no third-party import. The resident
loads it directly.
"""
from __future__ import annotations

import hashlib

__all__ = ["FakeSceneBackend"]


def _stable_offset(path: str, index: int) -> list:
    """A deterministic position for an object — a function of its name only,
    so the same recipe always builds the same scene."""
    digest = hashlib.sha256(f"{path}#{index}".encode("utf-8")).digest()
    return [
        round(int.from_bytes(digest[0:4], "big") / 65536.0, 6),
        round(int.from_bytes(digest[4:8], "big") / 65536.0, 6),
        round(index * 0.5, 6),
    ]


def _digest(obj) -> str:
    import json

    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class FakeSceneBackend:
    """A scene derived from the recipe, rebuilt per touched entry."""

    name = "fake"

    def __init__(self, pin: dict | None = None) -> None:
        self._pin = pin or {}
        self._document: dict = {"entries": {}}
        self._objects: list = []
        self._materials: list = []
        self._rebuilt_entries = 0

    # -- the seam ----------------------------------------------------------

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "engine": "fake-resident",
            "pin": self._pin,
            "capabilities": {
                "stages": True,
                "previews": True,
                "export_formats": ["usda", "glb"],
                "reexecute": "graph-edit",
            },
            "source": "fake-resident scene (deterministic; no engine behind it)",
        }

    def on_document(self, document: dict, touched: list) -> None:
        self._document = document
        entries = document.get("entries", {})
        # rebuild only what changed; the rest of the scene is left alone
        wanted = set(touched)
        self._objects = [o for o in self._objects if o["entry"] not in wanted]
        self._materials = [m for m in self._materials if m["entry"] not in wanted]
        for path in sorted(wanted):
            entry = entries.get(path)
            if entry is None:
                continue
            self._rebuilt_entries += 1
            self._materials.append(
                {"name": "mat_" + path.replace(".", "_"), "entry": path}
            )
            count = entry.get("params", {}).get("count", 1)
            try:
                count = max(int(count), 0)
            except (TypeError, ValueError):
                count = 1
            for index in range(count):
                self._objects.append(
                    {
                        "name": f"{path}.{index}",
                        "entry": path,
                        "location": _stable_offset(path, index),
                    }
                )

    def state(self) -> dict:
        return {
            "objects": sorted(self._objects, key=lambda o: o["name"]),
            "materials": sorted(self._materials, key=lambda m: m["name"]),
            "object_count": len(self._objects),
            "material_count": len(self._materials),
        }

    def stage(self, *, stage: str, dep_keys: list, version_hash: str) -> bytes:
        entries = self._document.get("entries", {})
        doc = {
            "engine": "fake-resident",
            "stage": stage,
            "version_hash": version_hash,
            "dep_keys": sorted(dep_keys),
            "entries": {path: _digest(entry) for path, entry in sorted(entries.items())},
            "scene": _digest(self.state()),
        }
        import json

        return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def preview(self, *, subject: str, rung: int, resolution: str, seed: int) -> bytes:
        body = (
            f"fake-resident preview · {subject} · rung {rung} · {resolution} · "
            f"seed {seed} · scene {_digest(self.state())[:16]}"
        )
        return f"{body} · sha:{hashlib.sha256(body.encode()).hexdigest()[:16]}".encode()

    def export(self, *, format: str, profile: str) -> bytes:
        import json

        doc = {
            "engine": "fake-resident",
            "format": format,
            "profile": profile,
            "objects": self.state()["objects"],
        }
        return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def stats(self) -> dict:
        return {
            "backend": self.name,
            "object_count": len(self._objects),
            "material_count": len(self._materials),
            "rebuilt_entries": self._rebuilt_entries,
        }
