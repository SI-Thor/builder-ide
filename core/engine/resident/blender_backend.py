"""The real engine's scene — Blender behind the resident seam (opt-in).

This is the backend that makes the warm scene server warm for real: a
``bpy`` scene held in a resident process, updated **in place** when the
recipe document moves. It needs ``bpy`` and therefore the engine's own
interpreter (``bpy==4.2.0`` pins Python 3.11; the core is 3.12), which is
why nothing imports it by default — the adapter starts it with::

    ResidentEngine(pin=..., root=..., backend="blender",
                   python=".../.venv/bin/python")   # the bpy interpreter

Standalone by design, like everything the worker loads: standard library
plus ``bpy``, no ``core`` import, 3.9-compatible syntax.

What is real here and what is named as missing:

* **real** — the scene is a real Blender scene (objects, meshes,
  materials), previews are real renders (Cycles through ``bpy.ops.render``,
  the only way ``bpy`` hands pixels back), exports are real
  ``ply``/``obj``/``usd`` writes, and the resident does Blender's
  save-time garbage collection itself with ``orphans_purge`` — a resident
  never saves, so nothing else would collect the orphans (WS §5.2).
* **the named missing piece** — ``stage`` is not yet an Infinigen stage:
  it evaluates the resident scene into a deterministic description
  (entry digests + scene digest), which proves the scene the stage read
  is the scene the recipe describes. The real stage runner
  (the fork's ``infinigen_thor.stage_runner``) is the same missing piece
  the v1 and v2 adapters name; it plugs into this backend's ``stage``
  without touching the adapter.

Determinism is the contract (rule 3: same request, same bytes), so every
placement and colour here is a pure function of the recipe — the same
document builds the same scene, in a fresh process or a recovered one.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile

__all__ = ["BlenderBackend"]

import bpy  # noqa: E402  (the engine's own interpreter; the opt-in gate)


def _hash_floats(seed: str, count: int) -> list:
    """A deterministic placement for one object — a pure function of its
    entry path and index, so the same recipe always builds the same
    scene, whichever process builds it."""
    digest = hashlib.sha256(f"{seed}#{count}".encode("utf-8")).digest()
    return [
        round(int.from_bytes(digest[0:4], "big") / 2**32, 6),
        round(int.from_bytes(digest[4:8], "big") / 2**32, 6),
        round(int.from_bytes(digest[8:12], "big") / 2**32, 6),
    ]


def _entry_color(path: str) -> tuple:
    digest = hashlib.sha256(path.encode("utf-8")).digest()
    return (
        0.2 + int.from_bytes(digest[0:2], "big") / 65535.0 * 0.6,
        0.2 + int.from_bytes(digest[2:4], "big") / 65535.0 * 0.6,
        0.2 + int.from_bytes(digest[4:6], "big") / 65535.0 * 0.6,
        1.0,
    )


RESOLUTIONS = {
    "270p": (480, 270), "480p": (854, 480), "720p": (1280, 720),
}


class BlenderBackend:
    """A real Blender scene derived from the recipe, rebuilt per touched
    entry — the fake backend's contract, with a real scene behind it."""

    name = "blender"

    def __init__(self, pin: dict | None = None) -> None:
        self._pin = pin or {}
        self._document: dict = {"entries": {}}
        self._rebuilt_entries = 0
        self._purges = 0
        self._cleared = False

    # -- the seam ----------------------------------------------------------

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "engine": "blender-resident",
            "blender": bpy.app.version_string,
            "pin": self._pin,
            "capabilities": {
                "stages": True,
                "previews": True,
                "export_formats": ["ply", "obj", "usd"],
                "reexecute": "graph-edit",
            },
            "source": (
                f"blender-resident scene · bpy {bpy.app.version_string} · "
                "real scene, real renders; the Infinigen stage runner is "
                "the named missing piece"
            ),
        }

    def on_document(self, document: dict, touched: list) -> None:
        """Bring the scene to the document — in place, for the touched
        entries only; the untouched objects are left exactly as they were."""
        self._document = document
        entries = document.get("entries", {})
        wanted = set(touched)

        if not self._cleared:
            # Blender's factory scene — a camera, a light, a cube — is part
            # of no recipe; the first load wipes it, the way the spike's
            # `butil.clear_scene` does before a stage runs.
            scene = bpy.context.scene
            for obj in list(scene.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            for blocks in (bpy.data.meshes, bpy.data.materials,
                           bpy.data.cameras, bpy.data.lights):
                for item in list(blocks):
                    blocks.remove(item)
            self._cleared = True

        scene = bpy.context.scene
        for obj in list(scene.objects):
            if obj.get("recipe_entry") in wanted:
                bpy.data.objects.remove(obj, do_unlink=True)
        for material in [
            m for m in bpy.data.materials
            if m.name.startswith("mat_") and m.name[4:].replace("_", ".")
            in wanted
        ]:
            bpy.data.materials.remove(material)

        for path in sorted(wanted):
            entry = entries.get(path)
            if entry is None:
                continue
            self._rebuilt_entries += 1
            count = self._entry_count(path, entry)
            material = self._material_for(path)
            for index in range(count):
                bpy.ops.mesh.primitive_cube_add(size=1.0,
                                                location=_hash_floats(path, index))
                obj = bpy.context.active_object
                obj.name = f"{path}.{index}"
                obj["recipe_entry"] = path
                obj.data.materials.append(material)

        # A resident never saves, so nothing else collects the datablocks
        # the rebuild orphans — this is Blender's save-time collection,
        # done by hand (WS §5.2: 209 meshes for 12 objects without it).
        self._purges += 1
        bpy.data.orphans_purge(do_recursive=True)

    def _entry_count(self, path: str, entry: dict) -> int:
        count = entry.get("params", {}).get("count", 1)
        try:
            return max(int(count), 0)
        except (TypeError, ValueError):
            return 1

    def _material_for(self, path: str):
        name = "mat_" + path.replace(".", "_")
        material = bpy.data.materials.get(name)
        if material is None:
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            node = next(
                (n for n in material.node_tree.nodes
                 if n.type == "BSDF_PRINCIPLED"), None)
            if node is not None:
                node.inputs["Base Color"].default_value = _entry_color(path)
        return material

    def state(self) -> dict:
        scene = bpy.context.scene
        objects = []
        for obj in sorted(scene.objects, key=lambda o: o.name):
            objects.append({
                "name": obj.name,
                "type": obj.type,
                "location": [round(float(v), 6) for v in obj.location],
                "materials": [s.material.name for s in obj.material_slots
                              if s.material is not None],
            })
        return {
            "objects": objects,
            "object_count": len(objects),
            "materials": sorted(m.name for m in bpy.data.materials),
            "meshes": len(bpy.data.meshes),
        }

    def stage(self, *, stage: str, dep_keys: list, version_hash: str) -> bytes:
        """One stage's output, evaluated against the resident scene.

        A deterministic description of the scene the recipe built — the
        entry digests and the scene digest — so a stage hit is byte
        identical across processes and recoveries (rule 3). The Infinigen
        stage runner replaces the body of this method, not its contract.
        """
        entries = self._document.get("entries", {})
        doc = {
            "engine": "blender-resident",
            "stage": stage,
            "version_hash": version_hash,
            "dep_keys": sorted(dep_keys),
            "blender": bpy.app.version_string,
            "entries": {
                path: hashlib.sha256(
                    json.dumps(entry, sort_keys=True,
                               default=str).encode("utf-8")
                ).hexdigest()
                for path, entry in sorted(entries.items())
            },
            "scene": hashlib.sha256(json.dumps(
                self.state(), sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        }
        return json.dumps(doc, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")

    def preview(self, *, subject: str, rung: int, resolution: str,
                seed: int) -> bytes:
        """A real render. The PNG is Blender's only way out, so it goes to
        a temp file and is read straight back (the spike's approach)."""
        width, height = RESOLUTIONS.get(resolution, RESOLUTIONS["480p"])
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"  # deterministic; GPU Cycles is not
        scene.cycles.samples = max(16, 16 * rung)
        scene.cycles.seed = seed
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.image_settings.file_format = "PNG"

        fd, path = tempfile.mkstemp(prefix="resident_preview_", suffix=".png")
        os.close(fd)
        try:
            scene.render.filepath = path
            bpy.ops.render.render(write_still=True)
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def export(self, *, format: str, profile: str) -> bytes:
        fmt = format.lower()
        writers = {
            "ply": bpy.ops.wm.ply_export,
            "obj": bpy.ops.wm.obj_export,
            "usd": bpy.ops.wm.usd_export,
        }
        if fmt not in writers:
            raise ValueError(
                f"the blender backend exports {sorted(writers)}, not {format!r}")
        fd, path = tempfile.mkstemp(prefix="resident_export_", suffix=f".{fmt}")
        os.close(fd)
        try:
            writers[fmt](filepath=path)
            with open(path, "rb") as fh:
                return fh.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def stats(self) -> dict:
        return {
            "backend": self.name,
            "object_count": len(bpy.context.scene.objects),
            "mesh_count": len(bpy.data.meshes),
            "material_count": len(bpy.data.materials),
            "rebuilt_entries": self._rebuilt_entries,
            "orphan_purges": self._purges,
        }
