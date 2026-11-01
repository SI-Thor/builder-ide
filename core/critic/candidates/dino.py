"""DINOv2-large features with a small probe per defect class.

The candidate is the cheapest model critic there is: a frozen vision encoder
and a **small head** on top of it, trained on the reference set itself.

Two things decide whether the number means anything, and both are in this
module:

* **the split.** A probe trained on the reference set and scored on the
  reference set measures nothing. The scored member must be *out* of the
  training set, and — this is the part that bites — so must its **base
  render**. Every base in the set contributes one defective member *and* one
  clean control, so a member-level leave-one-out leaves the clean control of
  the same base in the training set: the probe would be scored on a picture
  it has already seen a near-copy of. The default split is therefore
  **leave-one-base-out**, and the member-level split is available so the
  difference can be measured rather than argued about.
* **the head.** A class with two members has one positive left in the
  training set after the split. That is a fact about the reference set's
  size, not a bug in the probe, and the table shows what it costs.

The weights are the Thor's own copy of DINOv2-large (Apache-2.0, in the
local Hugging Face cache) — nothing is downloaded.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..checks import Thresholds
from ..critic import ReferenceCritic
from ..models import DEFECT_TARGETS, IMAGE_DEFECTS, CheckOutcome, CriticVerdict
from ..set import MemberRecipe

__all__ = [
    "DINO_MODEL",
    "DinoFeatures",
    "LinearProbe",
    "KnnProbe",
    "DinoProbeCritic",
]

#: The local weights: the Thor's Hugging Face cache copy, Apache-2.0.
DINO_MODEL = "facebook/dinov2-large"

#: The image classes a pixel probe can be asked about.
PROBE_CLASSES: tuple[str, ...] = tuple(IMAGE_DEFECTS)


# -- the features -------------------------------------------------------------


class DinoFeatures:
    """DINOv2-large's embedding of a picture.

    The encoder is frozen and loaded once; the features are cached on disk
    (``.npy``) so a re-run does not pay the forward pass again. The forward
    is the whole cost of this candidate, so the number of members matters
    more than the size of the head.
    """

    def __init__(
        self,
        *,
        model_id: str = DINO_MODEL,
        device: str = "cuda",
        cache_dir: str | Path | None = None,
        dtype: str = "bfloat16",
    ) -> None:
        self._model_id = model_id
        self._device = device
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._dtype = dtype
        self._model = None
        self._processor = None

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoImageProcessor, AutoModel

        self._torch = torch
        self._processor = AutoImageProcessor.from_pretrained(self._model_id)
        self._model = AutoModel.from_pretrained(
            self._model_id,
            dtype=getattr(torch, self._dtype),
        ).to(self._device)
        self._model.eval()

    def encode(self, image_path: str | Path) -> "Any":
        """The embedding of one picture: the CLS token and the patch mean."""
        import numpy as np

        path = Path(image_path)
        cached = self._cache_path(path)
        if cached is not None and cached.is_file():
            return np.load(cached)

        self._load()
        from PIL import Image

        image = Image.open(path).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt").to(self._device)
        with self._torch.no_grad():
            outputs = self._model(**inputs)
        # CLS token + the mean of the patch tokens: the standard DINOv2
        # descriptor, concatenated.
        cls = outputs.last_hidden_state[:, 0]
        patches = outputs.last_hidden_state[:, 1:].mean(dim=1)
        vector = self._torch.cat([cls, patches], dim=-1)[0].float().cpu().numpy()
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            np.save(cached, vector)
        return vector

    def _cache_path(self, image_path: Path) -> Path | None:
        if self._cache_dir is None:
            return None
        import hashlib

        digest = hashlib.sha256(str(image_path).encode("utf-8")).hexdigest()[:16]
        return self._cache_dir / f"{digest}.npy"


# -- the heads ----------------------------------------------------------------


@dataclass
class LinearProbe:
    """A binary logistic regression on the features, fitted in numpy.

    Small on purpose: one head per defect class, ``features`` weights each.
    With a training set of a dozen members the fit is regularised hard,
    because an unregularised head on a dozen points in 2 048 dimensions
    memorises the answer key.
    """

    weight: "Any"
    bias: float
    mean: "Any"
    scale: "Any"

    @staticmethod
    def fit(x: "Any", y: "Any", *, l2: float = 1e-2, steps: int = 600, lr: float = 0.5) -> "LinearProbe":
        import numpy as np

        mean = x.mean(axis=0)
        scale = x.std(axis=0)
        scale[scale < 1e-6] = 1.0
        z = (x - mean) / scale
        n, d = z.shape
        w = np.zeros(d, dtype=np.float64)
        b = 0.0
        for _ in range(steps):
            p = 1.0 / (1.0 + np.exp(-(z @ w + b)))
            grad = z.T @ (p - y) / n + l2 * w
            gbias = float((p - y).mean())
            w -= lr * grad
            b -= lr * gbias
        return LinearProbe(weight=w, bias=b, mean=mean, scale=scale)

    def probability(self, x: "Any") -> "Any":
        import numpy as np

        z = (x - self.mean) / self.scale
        return 1.0 / (1.0 + np.exp(-(z @ self.weight + self.bias)))


@dataclass
class KnnProbe:
    """A cosine k-nearest-neighbour head: the class of the nearest examples.

    With two examples in a class, a linear head is fitting noise; a nearest
    neighbour is the honest way to say "this picture looks like that one".
    """

    positives: "Any"
    negatives: "Any"

    @staticmethod
    def fit(x: "Any", y: "Any") -> "KnnProbe":
        import numpy as np

        positives = x[y > 0.5]
        negatives = x[y <= 0.5]
        return KnnProbe(positives=positives, negatives=negatives)

    def probability(self, x: "Any") -> "Any":
        import numpy as np

        def cosine(a: "Any", b: "Any") -> "Any":
            an = a / (np.linalg.norm(a, axis=-1, keepdims=True) + 1e-9)
            bn = b / (np.linalg.norm(b, axis=-1, keepdims=True) + 1e-9)
            return an @ bn.T

        if len(self.positives) == 0:
            return 0.0
        sim_pos = cosine(x, self.positives).max(axis=1)
        if len(self.negatives) == 0:
            return 1.0
        sim_neg = cosine(x, self.negatives).max(axis=1)
        # The probability that the picture is closer to the class's examples
        # than to anything else, squashed into (0, 1).
        margin = sim_pos - sim_neg
        return 1.0 / (1.0 + np.exp(-20.0 * margin))


# -- the candidate ------------------------------------------------------------


class DinoProbeCritic:
    """DINOv2-large features with one small head per defect class.

    ``split`` is the protocol:

    * ``"base"`` — leave-one-**base**-out (the default): the scored member
      and every member made from the same base render are out of the
      training set. This is the honest one.
    * ``"member"`` — leave-one-member-out: the scored member only. Kept so
      the leak can be measured.
    """

    name = "dino-probe"
    layers = ("image",)

    def __init__(
        self,
        *,
        members: Sequence[MemberRecipe] = (),
        features: Mapping[str, Any] | None = None,
        extractor: DinoFeatures | None = None,
        head: str = "knn",
        split: str = "base",
        classes: Sequence[str] = PROBE_CLASSES,
        threshold: float = 0.5,
        cache_dir: str | Path | None = None,
    ) -> None:
        if split not in ("base", "member"):
            raise ValueError(f"unknown split {split!r}; use 'base' or 'member'")
        if head not in ("linear", "knn"):
            raise ValueError(f"unknown head {head!r}; use 'linear' or 'knn'")
        self._members = list(members)
        self._features = dict(features or {})
        self._extractor = extractor
        self._head = head
        self._split = split
        self._classes = tuple(classes)
        self._threshold = threshold
        self._cache_dir = cache_dir

    @property
    def split(self) -> str:
        return self._split

    @property
    def head(self) -> str:
        return self._head

    def feature(self, member: MemberRecipe) -> "Any":
        """The member's embedding, extracted once and kept."""
        if member.member_id not in self._features:
            if self._extractor is None:
                raise RuntimeError("no feature extractor was given")
            if not member.derived_path:
                raise ValueError(f"member {member.member_id!r} has no derived image")
            self._features[member.member_id] = self._extractor.encode(
                member.derived_path
            )
        return self._features[member.member_id]

    def _training_set(self, member: MemberRecipe, defect: str) -> tuple["Any", "Any"]:
        """The training set for one class, with the scored member left out."""
        import numpy as np

        xs: list[Any] = []
        ys: list[float] = []
        for other in self._members:
            if other.layer != "image":
                continue
            if other.member_id == member.member_id:
                continue
            if self._split == "base" and other.base_id == member.base_id:
                # The plant's own base: its clean control is a near-copy of
                # the scored picture, and training on it is the leak.
                continue
            if other.member_id not in self._features:
                continue
            xs.append(self.feature(other))
            ys.append(1.0 if other.defect == defect else 0.0)
        if not xs:
            return np.zeros((0, 1)), np.zeros((0,))
        return np.stack(xs), np.asarray(ys, dtype=np.float64)

    def score(
        self,
        member: MemberRecipe,
        *,
        bases: Sequence[Any] = (),
        thresholds: Thresholds | None = None,
        cache_dir: str | Path | None = None,
        blender_python: str | None = None,
    ) -> CriticVerdict:
        """The probe's judgement of one frame, one head per class."""
        import numpy as np

        x = self.feature(member).reshape(1, -1)
        outcomes: list[CheckOutcome] = []
        for defect in self._classes:
            x_train, y_train = self._training_set(member, defect)
            positives = int((y_train > 0.5).sum())
            if positives == 0:
                # Nothing left of this class in the training set: the head
                # cannot be fitted, and the fold counts that as a miss
                # rather than as a pass.
                outcomes.append(
                    CheckOutcome(
                        check=DEFECT_TARGETS[defect],
                        fired=False,
                        detail=(
                            f"dino-probe: no training example of {defect!r} left "
                            f"after the {self._split!r} split"
                        ),
                        measured={"dino_positives": 0.0},
                        applicable=False,
                    )
                )
                continue
            if self._head == "linear":
                probe = LinearProbe.fit(x_train, y_train)
            else:
                probe = KnnProbe.fit(x_train, y_train)
            probability = float(np.asarray(probe.probability(x)).reshape(-1)[0])
            fired = probability >= self._threshold
            outcomes.append(
                CheckOutcome(
                    check=DEFECT_TARGETS[defect],
                    fired=fired,
                    detail=(
                        f"dino-probe({self._head}, {self._split} split): "
                        f"p({defect})={probability:.3f} >= {self._threshold} "
                        f"({positives} positive(s) in the training set)"
                    ),
                    measured={"dino_probability": probability},
                )
            )
        return CriticVerdict(
            member_id=member.member_id,
            base_id=member.base_id,
            defect=member.defect,
            checks=tuple(outcomes),
            label=f"verdict@{self.name}",
            degraded=self.name,
            layer=member.layer,
        )
