"""The workflows the night sends to ComfyUI.

The TRELLIS.2 environment (``~/lm-wt/trellis``) keeps its own API-format
workflows, and this seat reads them and patches the handful of inputs a
prop request changes: the prompt, the seeds, the image and the filename.
The environment is never modified — the template is read, its digest is
recorded, and a patched copy is what goes over the wire.

Reading the template rather than keeping a copy here is deliberate. A copy
would drift from the environment that actually runs, and the drift would
only show up as a mysterious failure at three in the morning. The digest
goes into the asset's provenance, so a prop made from a changed template is
visible in the record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "WorkflowError",
    "WorkflowTemplate",
    "build_image_workflow",
    "build_trellis_workflow",
    "load_template",
    "nodes_of_type",
    "trellis_seeds",
]


class WorkflowError(ValueError):
    """A workflow we cannot build from the template we were given."""


@dataclass(frozen=True)
class WorkflowTemplate:
    """A workflow read from disk, and the digest of the file it came from."""

    path: Path
    digest: str
    workflow: dict


def load_template(path: str | Path) -> WorkflowTemplate:
    """Read an API-format workflow template."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise WorkflowError(f"{path}: cannot be read ({exc})") from exc
    try:
        workflow = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"{path}: the template is not JSON ({exc})") from exc
    if not isinstance(workflow, dict):
        raise WorkflowError(f"{path}: the template is not a workflow")
    return WorkflowTemplate(
        path=path,
        digest=hashlib.sha256(raw).hexdigest(),
        workflow=workflow,
    )


def nodes_of_type(workflow: dict, class_type: str) -> list[tuple[str, dict]]:
    """The nodes of one class, in node-id order.

    Node ids are numbers in ComfyUI's API format, and the order they come
    back in is the order the graph was built in — which is how the three
    TRELLIS.2 samplers (structure, shape, texture) are told apart.
    """
    found = [
        (node_id, node)
        for node_id, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") == class_type
    ]

    def _key(item: tuple[str, dict]) -> tuple[int, str]:
        node_id = item[0]
        try:
            return (int(node_id), node_id)
        except ValueError:
            return (0, node_id)

    return sorted(found, key=_key)


def _one(workflow: dict, class_type: str) -> tuple[str, dict]:
    found = nodes_of_type(workflow, class_type)
    if not found:
        raise WorkflowError(f"the template has no {class_type} node")
    return found[0]


def trellis_seeds(seed: int) -> tuple[int, int, int]:
    """The three seeds one variant uses: structure, shape and texture.

    They are derived from the variant's seed so the night's work replays,
    and they are spread apart because the three stages are three different
    networks and feeding them the same number buys nothing.
    """
    out = []
    for label in ("structure", "shape", "texture"):
        digest = hashlib.blake2b(
            f"{label}:{seed}".encode("utf-8"), digest_size=8
        ).digest()
        out.append(int.from_bytes(digest, "big") % (2**31 - 1))
    return (out[0], out[1], out[2])


def build_image_workflow(
    template: WorkflowTemplate,
    *,
    prompt: str,
    negative: str,
    seed: int,
    size: int,
    steps: int,
    cfg: float,
    sampler: str,
    scheduler: str,
    filename_prefix: str,
) -> dict:
    """The image stage: a concept prompt, and a picture of it.

    The template's two text encoders are taken in node order — the first is
    the concept, the second is what the picture must not be.
    """
    workflow = json.loads(json.dumps(template.workflow))
    encoders = nodes_of_type(workflow, "CLIPTextEncode")
    if len(encoders) != 2:
        raise WorkflowError(
            f"the image template has {len(encoders)} text encoders; "
            "this seat expects one for the concept and one for the negative"
        )
    (_, positive), (_, negative_node) = encoders
    positive["inputs"]["text"] = prompt
    negative_node["inputs"]["text"] = negative

    _, latent = _one(workflow, "EmptyLatentImage")
    latent["inputs"]["width"] = size
    latent["inputs"]["height"] = size

    _, ksampler = _one(workflow, "KSampler")
    ksampler["inputs"]["seed"] = int(seed)
    ksampler["inputs"]["steps"] = int(steps)
    ksampler["inputs"]["cfg"] = float(cfg)
    ksampler["inputs"]["sampler_name"] = sampler
    ksampler["inputs"]["scheduler"] = scheduler

    _, save = _one(workflow, "SaveImage")
    save["inputs"]["filename_prefix"] = filename_prefix
    return workflow


def build_trellis_workflow(
    template: WorkflowTemplate,
    *,
    image_name: str,
    seeds: tuple[int, int, int],
    steps: tuple[int, int, int],
    cfg: float,
    sampler: str,
    scheduler: str,
    filename_prefix: str,
    resolution: int = 32,
) -> dict:
    """The mesh stage: a picture, and a mesh of it.

    The three samplers are the structure, shape and texture stages, in node
    order, and each gets its own seed.
    """
    workflow = json.loads(json.dumps(template.workflow))
    _, load = _one(workflow, "LoadImage")
    load["inputs"]["image"] = image_name

    samplers = nodes_of_type(workflow, "KSampler")
    if len(samplers) < 3:
        raise WorkflowError(
            f"the mesh template has {len(samplers)} samplers; "
            "the structure, shape and texture stages need three"
        )
    for index, ((_, node), seed, stage_steps) in enumerate(
        zip(samplers[:3], seeds, steps)
    ):
        node["inputs"]["seed"] = int(seed)
        node["inputs"]["steps"] = int(stage_steps)
        node["inputs"]["sampler_name"] = sampler
        node["inputs"]["scheduler"] = scheduler
        if index < 2:
            # The structure and the shape stage take the request's CFG. The
            # texture stage does not: the template gives it 1.0, and the
            # CFGOverride nodes on either side of it set the rest of its
            # schedule. Changing it would change the texture, not sharpen it.
            node["inputs"]["cfg"] = float(cfg)

    _, decode = _one(workflow, "VaeDecodeStructureTrellis2")
    # The resolution is a combo widget, and a combo's value is its label:
    # the string "32", not the number 32. ComfyUI refuses the prompt
    # otherwise, and says so only in its log.
    decode["inputs"]["resolution"] = str(resolution)

    _, save = _one(workflow, "SaveGLB")
    save["inputs"]["filename_prefix"] = filename_prefix
    return workflow
