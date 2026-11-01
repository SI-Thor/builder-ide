import pathlib

p = pathlib.Path("/home/proart/lm-wt/clef-cascade/scripts/tasks.py")
lines = p.read_text().splitlines(keepends=True)

# Replace lines 234..317 (1-indexed) -- the image-measurement T2 block and
# defect_state_text -- with the text-description T2 variant.
start = 234 - 1
end = 317  # inclusive of line 317

NEW = '''#: How each defect class LOOKS, written so the symptom does not lexically
#: echo the class name: the model has to know the critic's taxonomy, not
#: string-match the label.  One sentence per class, fixed.
DEFECT_SYMPTOM: dict[str, str] = {
    "none": (
        "Nothing was tampered with: the frame carries its intended values "
        "throughout, every object is present and seated on the ground, the "
        "shapes are the right size and closed, and the surface is smooth."),
    "black_frame": (
        "Every one of the pixels in the frame holds the same value, so the "
        "render came back as one uniform field with no structure in it at all."),
    "noise_fireflies": (
        "Hundreds of individual pixels deviate from all of their neighbours "
        "by the full possible range, each one standing alone, surrounded by "
        "the ordinary values."),
    "missing_object": (
        "One of the things that belongs in the scene is simply not there; "
        "everything else rendered normally."),
    "holes": (
        "Parts of the surface are punched through, so patches of the object "
        "are absent and the background shows through where material should be."),
    "texture_swap": (
        "The material on the object is from a different asset than the one it "
        "should be wearing; the geometry is right but the surface finish is "
        "somebody else's."),
    "floating_object": (
        "An object hangs in mid-air, detached from the ground it should be "
        "resting on, casting its shadow onto nothing."),
    "wrong_scale": (
        "The object was built at the wrong size: its proportions are right but "
        "it is much larger or much smaller than the scene it sits in."),
    "hollow_mesh": (
        "The object is only a shell: it looks solid from the outside but has "
        "no interior, so it is open inside and back-faces are visible."),
    "clipped_geometry": (
        "A slice of the geometry has been cut away, so the object ends in a "
        "flat open cross-section instead of closing."),
}


def _member_recipe_text(recipe: dict[str, Any] | None) -> list[str]:
    """The recipe's own numbers, as neutral facts about the artefact."""
    if not recipe:
        return []
    out = []
    for k in sorted(recipe):
        if k in ("kind", "base_mesh", "base_sha256"):
            continue
        v = recipe[k]
        if isinstance(v, (list, tuple)):
            v = "/".join(str(x) for x in v)
        out.append(f"{k}={v}")
    return out


def build_defect_cases(max_bases: int = 30) -> list[dict[str, Any]]:
    """The reference set as classification cases, with ground truth.

    The ProArt has no copy of the critic's rendered images or meshes (they
    live on the Thor), so this is the *text-description* variant the brief
    asks for: every member of builder-ide's reference set becomes one case
    whose state describes the artefact in symptom terms, and the question
    asks which defect class it carries.  Clean bases are the 'none' class,
    so a model that always says "some defect" is punished for it.

    Same members, same classes, same clean controls as the Thor-side
    measurement variant -- only the input surface differs.
    """
    if not REFERENCE_SET.exists():
        return []
    ref = json.loads(REFERENCE_SET.read_text())
    cases: list[dict[str, Any]] = []

    bases_by_id = {b["id"]: b for b in ref["bases"]}

    for m in ref["members"]:
        truth = m.get("defect") or "none"
        base = bases_by_id.get(m.get("base_id"), {})
        state_lines = [DEFECT_SYMPTOM[truth]]
        state_lines.append(
            f"Scene family: {base.get('scene', 'unknown')}; "
            f"frame size {base.get('width', '?')}x{base.get('height', '?')}.")
        state_lines.append(
            f"The change was made to the {m.get('layer', '?')} layer of "
            f"member {m.get('member_id', '?')}.")
        for line in _member_recipe_text(m.get("recipe")):
            state_lines.append("Detail: " + line + ".")
        cases.append({
            "id": m["member_id"],
            "state": "\\n".join(state_lines),
            "truth": truth,
            "source": "member",
            "layer": m.get("layer"),
        })

    # Clean controls: the bases, so the model can say "none".
    for b in ref["bases"][:max_bases]:
        state_lines = [DEFECT_SYMPTOM["none"]]
        state_lines.append(
            f"Scene family: {b.get('scene', 'unknown')}; "
            f"frame size {b.get('width', '?')}x{b.get('height', '?')}.")
        state_lines.append(
            f"The change was made to the image layer of member "
            f"clean-{b.get('id', '?')}.")
        cases.append({
            "id": f"clean-{b['id']}",
            "state": "\\n".join(state_lines),
            "truth": "none",
            "source": "base",
            "layer": "image",
        })
    return cases


def defect_state_text(meas: dict[str, Any] | str) -> str:
    """The case's state as plain text a decision model can read."""
    if isinstance(meas, str):
        return meas
    lines = ["A rendered scene was measured by the critic's checks.",
             "Each check below is one measurement and whether it fired."]
    for check in sorted(meas.keys()):
        d = meas[check]
        m = d.get("measured") or {}
        ms = ", ".join(f"{k}={v:g}" for k, v in sorted(m.items()))
        lines.append(f"check {check}: fired={d.get('fired')} measured[{ms}]")
    return "\\n".join(lines)
'''

out = lines[:start] + [NEW] + lines[end:]
p.write_text("".join(out))
print("patched: replaced lines", 234, "-", 317)
