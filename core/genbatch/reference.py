"""The reference set the plausibility prior is fitted on.

**Why the set is two things.** The prior is a prior over the features of
**real objects**, and it can only be that if the real objects are in it. A
prior fitted on generated props alone called **every** one of the 38
sampled real SimReady assets a ghost: the generated props are solids and a
real mug is a shell, so the measure the prior read — the shell's own
signed volume over its box — said 0.05 for the mug and 0.68 for the toy
(docs/lab/exp-critic-shells.md).

So the reference set is the **union**: the approved assets the library has
accepted, and the real objects, measured by the same pipeline. The real
objects live in :mod:`core.genbatch.simready-reference.json` — 38 rows of
six numbers each, where the dataset itself is 113.9 MiB of GLBs that are
not in this repository.

**The fit is a recipe, not a file.** :data:`REFERENCE_CLUSTERS` and
:data:`REFERENCE_SEED` are the numbers the measurement chose, and
:func:`union_prior` puts the two halves together. The same set and the
same numbers give the same prior: a rebuild gives the same answer.

**Credit.** The real objects are NVIDIA SimReady Assets
(``nvidia/simready-assets`` on Hugging Face), CC-BY-4.0, read and sampled
— never mirrored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from core.genbatch.plausibility import FEATURE_NAMES, PropFeatures, ReferencePrior

__all__ = [
    "GHOST_THRESHOLD",
    "REAL_KIND",
    "REFERENCE_CLUSTERS",
    "REFERENCE_FILL_METHOD",
    "REFERENCE_SEED",
    "ReferenceAsset",
    "reference_document",
    "simready_features",
    "simready_reference",
    "union_prior",
]

#: Where the measured real objects live.
REFERENCE_FILE = Path(__file__).with_name("simready-reference.json")

#: The fill measure the reference set was measured with, and therefore the
#: one an incoming prop has to be measured with to be comparable.
REFERENCE_FILL_METHOD = "convex"

#: The prior's cluster count, and its seed. The cluster count is the
#: fallback: when the kinds are known, the groups *are* the kinds and the
#: count is not used (docs/lab/exp-critic-shells.md).
REFERENCE_CLUSTERS = 22
REFERENCE_SEED = 20261031

#: The kind the sampled real objects belong to. The sample is 37
#: categories for 38 packages, so a category is a kind of one object — and
#: a kind of one cannot express the threshold: the score is a rank inside
#: a kind, so a kind of n cannot score below 0.5/(n+1) and the threshold
#: needs ten members. The real objects are one kind: *a real object*.
REAL_KIND = "real"

#: The score below which a prop is called a ghost.
GHOST_THRESHOLD = 0.05


@dataclass(frozen=True)
class ReferenceAsset:
    """One measured real object, and the measurement that produced it."""

    #: The asset's name in the dataset.
    name: str
    #: The six features the prior is over.
    features: PropFeatures
    #: How many triangles the whole asset has.
    triangles: int
    #: Whether the whole asset is a closed surface.
    watertight: bool

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "features": dict(zip(FEATURE_NAMES, self.features.as_vector())),
            "triangles": self.triangles,
            "watertight": self.watertight,
        }


def reference_document(path: Path | None = None) -> dict:
    """The reference file, as it is on disk."""
    target = Path(path) if path is not None else REFERENCE_FILE
    return json.loads(target.read_text(encoding="utf-8"))


def simready_reference(path: Path | None = None) -> list[ReferenceAsset]:
    """The measured real objects, in the order the file lists them."""
    document = reference_document(path)
    assets: list[ReferenceAsset] = []
    for row in document["assets"]:
        features = row["features"]
        assets.append(
            ReferenceAsset(
                name=row["name"],
                features=PropFeatures(
                    log_volume=float(features["log_volume"]),
                    sphericity=float(features["sphericity"]),
                    elongation=float(features["elongation"]),
                    fill_ratio=float(features["fill_ratio"]),
                    offcentre=float(features["offcentre"]),
                    defect_rate=float(features["defect_rate"]),
                ),
                triangles=int(row["triangles"]),
                watertight=bool(row["watertight"]),
            )
        )
    return assets


def simready_features(path: Path | None = None) -> list[PropFeatures]:
    """The real objects' features, and nothing else."""
    return [asset.features for asset in simready_reference(path)]


def union_prior(
    approved: Sequence[PropFeatures],
    labels: Sequence[str] | None = None,
    *,
    clusters: int = REFERENCE_CLUSTERS,
    seed: int = REFERENCE_SEED,
    path: Path | None = None,
) -> ReferencePrior:
    """The prior, fitted on the approved set **and** the real objects.

    ``approved`` is the set of props the library has accepted — the toy
    set in the tests, the store's approved members in a night. The real
    objects are added to it, so that the prior knows what a shell looks
    like as well as what a solid looks like.

    ``labels`` says what kind each approved object is, and the groups are
    those kinds: the real objects are one kind (:data:`REAL_KIND`), and the
    approved set's own kinds are the caller's. Without labels the prior
    falls back to the k-means grouping and the cluster count.

    The cluster count and the seed default to the measured ones; a caller
    that wants a different fit can ask for one, and the measurement in
    ``docs/lab/exp-critic-shells.md`` says what each choice does.
    """
    real = simready_features(path)
    reference = list(approved) + real
    if labels is None:
        return ReferencePrior(reference, clusters=clusters, seed=seed)
    kinds = list(labels) + [REAL_KIND] * len(real)
    return ReferencePrior(reference, clusters=clusters, seed=seed, labels=kinds)
