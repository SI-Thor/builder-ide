"""The plausibility side of the prop critic: a prior over real-object features.

**What the critic has today, and what it cannot see.** Every check in
:mod:`core.genbatch.critic` asks whether the prop is a *valid solid*: is it
watertight, does it fill its box, is its surface big enough for its volume,
does its mass sit inside it. Those are real checks and they catch a broken
mesh. None of them asks whether the shape is the kind of shape a real
object has.

The repair-fidelity check is a **consistency** check — the silhouette IoU
between the repaired mesh and the mesh the generator handed over. It says
"the repair did not quietly reshape the prop". It does not say the prop is
a thing that could exist.

**Consistency is not plausibility, and a consistency-only critic certifies
ghosts.** A generator that satisfies the measurement perfectly and produces
an object no camera has ever seen passes every check in the current
critic. The other side of the judge is missing, and this module is it.

**What the other side is.** A *prior over the features of real objects*,
fitted on the approved assets — the props the library accepted. A prop is
plausible when it looks like the things that have been approved: a volume
in the range real things have, a surface-to-volume ratio real things have,
proportions real things have. The prior is **multimodal by construction**:
the approved set is grouped (a mug and a plank are not the same kind of
object), and a prop is compared with the group it most resembles. A single
Gaussian over the pooled set would call half of every real object's class
implausible, which is the failure mode of "one distribution over a
multimodal world".

**The ambiguity gate.** TRELLIS.2 turns an image into a mesh, and that is
an inverse problem: one picture admits many shapes. The set of shapes
consistent with a picture is a **fiber**, and a wide fiber means the
picture did not determine the shape. The seat already generates N
reconstructions of the same request (the night's seeds), so the fiber's
width is **measured**, not assumed: it is how much the reconstructions
disagree, in the same units the approved assets disagree in. A wide fiber
is not a bad prop — it is an **ambiguous** one, and the right verdict is
*escalate* (another seed, another model, or a question), not *accept* and
not *reject*.

**The weighting, measured rather than guessed.** The two sides do not come
out of the same kind of number: the consistency score is a silhouette IoU,
which lives near 1 and saturates there, and the plausibility score is a
percentile over the approved set, which spreads over the whole range. Add
them with a hand-picked weight and the side that happens to spread wider
silently wins. So both sides are put on **the approved set's own scale**
first — each becomes a percentile among real objects — and the scale gap
that was closed is **measured and reported** rather than left implicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from core.genbatch.mesh import MeshReport

__all__ = [
    "FEATURE_NAMES",
    "PropFeatures",
    "ReferencePrior",
    "TwoSidedVerdict",
    "features_from_report",
    "fiber_width",
    "judge",
    "percentile_against",
    "tail_probability",
]

#: The features the prior is over, in the order they are stored.
FEATURE_NAMES: tuple[str, ...] = (
    "log_volume",
    "sphericity",
    "elongation",
    "fill_ratio",
    "offcentre",
    "defect_rate",
)

#: A sphere's surface-to-volume ratio, scaled: ``4 pi r^2 / ((4/3) pi r^3)^(2/3)``.
#: The tightest bound a closed solid's surface can have for its volume.
SPHERE_RATIO = 4.836


@dataclass(frozen=True)
class PropFeatures:
    """The measurable facts about a prop's shape.

    Every feature is a number a real object has a range for and a ghost
    usually does not. They are all derived from what the mesh layer already
    measures (:class:`~core.genbatch.mesh.MeshReport`), so nothing here
    needs a second pass over the geometry.
    """

    #: How big the thing is. Logarithmic, because a mug and a cathedral are
    #: both ordinary and their volumes differ by nine orders of magnitude.
    log_volume: float
    #: ``area / volume^(2/3)`` — 4.836 for a sphere, higher for anything
    #: with a surface. A shape far below the sphere's bound is not
    #: measuring what it thinks it is.
    sphericity: float
    #: Longest axis over shortest. A real object has a range; a noise blob
    #: is round in every direction and a splinter is not round at all.
    elongation: float
    #: The volume over the bounding box's volume. A solid fills a good part
    #: of its box; a shell fills almost none of it.
    fill_ratio: float
    #: How far the centre of mass sits from the middle of the box, in
    #: diagonals. A real object is roughly where it looks like it is.
    offcentre: float
    #: The share of the mesh's triangles that are holes, seams or flat.
    defect_rate: float

    def as_vector(self) -> np.ndarray:
        """The features as a vector, in :data:`FEATURE_NAMES` order."""
        return np.array(
            [
                self.log_volume,
                self.sphericity,
                self.elongation,
                self.fill_ratio,
                self.offcentre,
                self.defect_rate,
            ],
            dtype=np.float64,
        )

    @classmethod
    def from_vector(cls, values: Sequence[float]) -> "PropFeatures":
        """The features from a vector, in :data:`FEATURE_NAMES` order."""
        return cls(*(float(value) for value in values))


def features_from_report(report: MeshReport) -> PropFeatures:
    """The features of a measured mesh.

    A mesh that is not a closed solid still gets features — the numbers are
    what they are, and a ghost with a broken surface should be judged on
    its surface too.
    """
    volume = max(float(report.volume), 1e-12)
    area = max(float(report.area), 0.0)
    extent = [max(float(axis), 1e-12) for axis in report.extent]
    longest = max(extent)
    shortest = min(extent)
    box_volume = max(extent[0] * extent[1] * extent[2], 1e-12)
    diagonal = max(float(report.diagonal), 1e-12)

    centre = np.asarray(report.centre_of_mass, dtype=np.float64)
    box_centre = (
        np.asarray(report.bbox_min, dtype=np.float64)
        + np.asarray(report.bbox_max, dtype=np.float64)
    ) / 2.0
    offcentre = float(np.linalg.norm(centre - box_centre) / diagonal)

    triangles = max(int(report.triangles), 1)
    defects = (
        int(report.boundary_edges)
        + int(report.nonmanifold_edges)
        + int(report.degenerate_triangles)
    )

    return PropFeatures(
        log_volume=float(np.log(volume)),
        sphericity=area / (volume ** (2.0 / 3.0)),
        elongation=longest / shortest,
        fill_ratio=volume / box_volume,
        offcentre=offcentre,
        defect_rate=defects / triangles,
    )


def percentile_against(value: float, population: Sequence[float]) -> float:
    """Where a value sits among a population, as a mid-p percentile.

    One-sided: the share of the population below the value. This is the
    right reading for the **consistency** side, where more is better: a
    prop that matches its image better than most real objects do is high
    in the percentile, and the comparison is on the population's scale
    however tightly the raw scores bunch up.

    The mid-p correction (adding half a count on each side) keeps the
    result strictly inside (0, 1): a percentile of exactly zero would make
    a geometric mean undefined, and one of exactly one would hide a value
    that is merely the largest of a small set.
    """
    if not population:
        raise ValueError("a percentile needs a population")
    below = sum(1 for other in population if other < value)
    equal = sum(1 for other in population if other == value)
    return (below + 0.5 * equal + 0.5) / (len(population) + 1.0)


def tail_probability(value: float, population: Sequence[float]) -> float:
    """How typical a value is, counting both tails.

    Two-sided: the smaller of the two tail probabilities, doubled. A value
    in the middle of the population scores near 1 — it is as ordinary as
    the population's own centre — and a value far outside it, **in either
    direction**, scores near 0.

    This is the reading the plausibility side needs, and the one-sided
    percentile gets it wrong: a prop with a surface-to-volume ratio of 30
    is *extreme*, and a percentile would call it the most ordinary value
    in the set, because it is above everything. Extreme in either
    direction is what makes a shape a ghost.
    """
    if not population:
        raise ValueError("a tail probability needs a population")
    count = len(population)
    below = sum(1 for other in population if other < value)
    equal = sum(1 for other in population if other == value)
    above = count - below - equal
    lower = (below + 0.5 * equal + 0.5) / (count + 1.0)
    upper = (above + 0.5 * equal + 0.5) / (count + 1.0)
    return float(min(1.0, 2.0 * min(lower, upper)))


@dataclass(frozen=True)
class PlausibilityScore:
    """How ordinary a prop looks, and beside what."""

    #: The share of the approved objects of this prop's own kind that are
    #: **at least as atypical** as it is — a p-value for atypicality. A prop
    #: in the middle of its kind scores around one half; a prop nothing
    #: else resembles scores near zero.
    score: float
    #: Which group of approved objects it resembles.
    cluster: int
    #: The per-feature tail probabilities, within that group.
    percentiles: tuple[float, ...]
    #: The standardised distance to that group's centre. A prop far from
    #: every centre is off the manifold of real objects.
    distance: float


class ReferencePrior:
    """A prior over the features of real objects.

    Fitted on the approved assets. The set is **grouped** first (k-means on
    the standardised features, seeded, so the fit is reproducible), and each
    group keeps its own per-feature percentiles. A prop is compared with
    the group it most resembles — which is what makes the prior multimodal
    in the way the world is: a plank and a mug are both ordinary, and a
    single distribution over the pooled set would call one of them a ghost.
    """

    def __init__(
        self,
        reference: Sequence[PropFeatures],
        *,
        clusters: int = 2,
        seed: int = 0,
    ) -> None:
        if len(reference) < 2:
            raise ValueError("a prior needs at least two approved objects")
        if clusters < 1:
            raise ValueError("clusters is a count")
        self.reference = tuple(reference)
        self._matrix = np.array(
            [features.as_vector() for features in self.reference], dtype=np.float64
        )
        self._centre = self._matrix.mean(axis=0)
        spread = self._matrix.std(axis=0)
        self._scale = np.where(spread > 1e-12, spread, 1.0)
        self._standardised = (self._matrix - self._centre) / self._scale

        self._centroids, self._assignment = self._fit(
            self._standardised, min(clusters, len(self.reference)), seed
        )
        self._groups: list[np.ndarray] = [
            self._standardised[self._assignment == index]
            for index in range(self._centroids.shape[0])
        ]
        self._group_sizes = [len(group) for group in self._groups]
        # How atypical each approved object is within its own group. This
        # population is what the prop's own atypicality is ranked against.
        self._atypicality = np.array(
            [
                self._atypicality_of(row)
                for row in self._standardised
            ],
            dtype=np.float64,
        )
        self._group_atypicality = [
            self._atypicality[self._assignment == index].tolist()
            for index in range(self._centroids.shape[0])
        ]
        self._plausibility = np.array(
            [self._raw_score(row) for row in self._standardised], dtype=np.float64
        )

    def _atypicality_of(self, row: np.ndarray) -> float:
        """The atypicality of a reference member within its own group."""
        cluster, group = self._nearest_group(row)
        if len(group) == 0:
            return 0.0
        return self._atypicality_index(row, group)

    # -- the fit ---------------------------------------------------------------

    def _fit(
        self, points: np.ndarray, clusters: int, seed: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """k-means with a seeded, furthest-point initialisation.

        Seeded so the prior is the same object twice — the house rule that
        a rebuild gives the same answer.
        """
        rng = np.random.default_rng(seed)
        centres = np.empty((clusters, points.shape[1]), dtype=np.float64)
        first = int(rng.integers(points.shape[0]))
        centres[0] = points[first]
        for index in range(1, clusters):
            distances = np.min(
                np.linalg.norm(points[:, None, :] - centres[None, :index, :], axis=2),
                axis=1,
            )
            # The furthest point from every centre so far: a k-means++
            # approximation that needs no randomness beyond the first pick.
            centres[index] = points[int(np.argmax(distances))]
        assignment = np.zeros(points.shape[0], dtype=np.int64)
        for _ in range(50):
            distances = np.linalg.norm(
                points[:, None, :] - centres[None, :, :], axis=2
            )
            new_assignment = np.argmin(distances, axis=1)
            if np.array_equal(new_assignment, assignment):
                break
            assignment = new_assignment
            for index in range(clusters):
                members = points[assignment == index]
                if len(members):
                    centres[index] = members.mean(axis=0)
        distances = np.linalg.norm(
            points[:, None, :] - centres[None, :, :], axis=2
        )
        return centres, np.argmin(distances, axis=1)

    def _tails(self, row: np.ndarray, group: np.ndarray) -> np.ndarray:
        """The per-feature tail probabilities of one row within a group."""
        return np.array(
            [
                tail_probability(float(value), group[:, index].tolist())
                for index, value in enumerate(row)
            ],
            dtype=np.float64,
        )

    def _atypicality_index(self, row: np.ndarray, group: np.ndarray) -> float:
        """How atypical one row is within its group.

        The geometric mean of the per-feature tails, so **one impossible
        feature is not averaged away by five ordinary ones**.

        The geometric mean is the right *statistic* and the wrong *scale*:
        multiplying six independent tails lands a perfectly ordinary prop
        near 0.2, because the probability that six independent features are
        all within one and a half sigma is small. So the statistic is not
        reported as the score — it is compared with the approved set's own
        distribution of it, and that comparison is the score.
        """
        tails = self._tails(row, group)
        logs = np.log(np.clip(tails, 1e-12, None))
        return float(np.exp(logs.mean()))

    def _nearest_group(self, row: np.ndarray) -> tuple[int, np.ndarray]:
        """Which group of approved objects a row resembles, and the group."""
        distances = np.linalg.norm(self._centroids - row[None, :], axis=1)
        cluster = int(np.argmin(distances))
        return cluster, self._groups[cluster]

    def _raw_score(self, row: np.ndarray) -> float:
        """The plausibility of one reference member: its atypicality's rank.

        The share of its own group's approved objects that are **at least
        as atypical** as it is — a p-value for atypicality. A prop in the
        middle of its kind scores around one half; a prop nothing else
        resembles scores near zero.
        """
        cluster, group = self._nearest_group(row)
        if len(group) == 0:
            return 0.0
        atypicality = self._atypicality_index(row, group)
        return percentile_against(atypicality, self._group_atypicality[cluster])

    # -- the reads -------------------------------------------------------------

    @property
    def feature_scales(self) -> tuple[float, ...]:
        """The spread of each feature over the approved set."""
        return tuple(float(value) for value in self._scale)

    @property
    def group_sizes(self) -> tuple[int, ...]:
        """How many approved objects are in each group."""
        return tuple(int(size) for size in self._group_sizes)

    @property
    def ordinary_width(self) -> float:
        """How far apart real objects of the same kind usually are.

        This is the yardstick the ambiguity gate uses: the reconstructions
        of one image disagree by more than this, and the image did not
        determine the shape. It is read off the approved set, so no magic
        number is involved.
        """
        spreads = []
        for group in self._groups:
            if len(group) < 2:
                continue
            centre = group.mean(axis=0)
            spreads.append(float(np.mean(np.linalg.norm(group - centre, axis=1))))
        if not spreads:
            return 0.0
        return float(np.quantile(np.asarray(spreads), 0.9))

    def score(self, features: PropFeatures) -> PlausibilityScore:
        """How ordinary a prop looks, and beside what."""
        row = (features.as_vector() - self._centre) / self._scale
        distances = np.linalg.norm(self._centroids - row[None, :], axis=1)
        cluster = int(np.argmin(distances))
        group = self._groups[cluster]
        if len(group) == 0:
            return PlausibilityScore(
                score=0.0, cluster=cluster, percentiles=(0.0,) * len(row), distance=0.0
            )
        tails = tuple(float(value) for value in self._tails(row, group))
        atypicality = self._atypicality_index(row, group)
        score = percentile_against(atypicality, self._group_atypicality[cluster])
        return PlausibilityScore(
            score=float(score),
            cluster=cluster,
            percentiles=tails,
            distance=float(distances[cluster]),
        )

    def plausibility_spread(self) -> float:
        """The spread of the plausibility score over the approved set.

        This is one half of the measured scale gap: it says how much room
        the plausibility side has to move, and therefore how much a
        hand-picked weight would have given it.
        """
        if len(self._plausibility) < 2:
            return 0.0
        return float(self._plausibility.std(ddof=1))

    def consistency_gap(self, consistency_population: Sequence[float]) -> float:
        """The scale gap between the two sides, as it stands before balancing.

        The consistency side's spread over the approved set divided by the
        plausibility side's. A silhouette IoU lives near 1 and saturates
        there, so this number is usually small — and a small number here
        means the consistency side would have been almost ignored by any
        fixed weighting.
        """
        if len(consistency_population) < 2:
            return 0.0
        spread = float(np.std(np.asarray(consistency_population, dtype=np.float64), ddof=1))
        plausibility = self.plausibility_spread()
        if plausibility <= 0.0:
            return 0.0
        return spread / plausibility


def fiber_width(
    reconstructions: Sequence[PropFeatures], prior: ReferencePrior
) -> float:
    """How much the reconstructions of one image disagree.

    The image admits a set of shapes — the **fiber** — and the night
    already draws N of them (the seeds). The width of the fiber is the
    disagreement between them, measured in the same standardised units the
    approved set uses, so the two numbers can be compared.

    One reconstruction cannot disagree with anything: the width of a fiber
    needs at least two samples, and a single sample is reported as
    ``nan`` rather than as zero, because zero would read as "certain" when
    it means "not measured".
    """
    if len(reconstructions) < 2:
        return float("nan")
    rows = np.array(
        [
            (features.as_vector() - prior._centre) / prior._scale
            for features in reconstructions
        ],
        dtype=np.float64,
    )
    centre = rows.mean(axis=0)
    return float(np.mean(np.linalg.norm(rows - centre, axis=1)))


@dataclass(frozen=True)
class TwoSidedVerdict:
    """The two-sided judgement: does the prop match, and is it a thing?

    ``consistency`` is the raw consistency score the caller measured (the
    silhouette IoU, say). ``plausibility`` is the prior's reading of the
    prop's features. ``combined`` is the two of them on one scale, each as
    a percentile among real objects, combined as a weighted geometric
    mean — so a prop that is perfect on one side and terrible on the other
    does not average out.

    ``ambiguous`` is the fiber-width gate: the reconstructions of this
    image disagree so much that the image did not determine the shape. That
    is a reason to **escalate**, not to accept and not to reject.

    ``gap`` is the measured scale gap that the balancing closed — the number
    that says how much the hand-picked weight would have mattered.
    """

    consistency: float
    plausibility: float
    combined: float
    ambiguous: bool = False
    escalate: bool = False
    reason: str = ""
    gap: float = 0.0

    def line(self) -> str:
        """The one line the morning can show."""
        return (
            f"consistency {self.consistency:.4f} · "
            f"plausibility {self.plausibility:.4f} · "
            f"two-sided {self.combined:.4f}"
            + (" · AMBIGUOUS" if self.ambiguous else "")
        )


def judge(
    *,
    features: PropFeatures,
    consistency: float,
    prior: ReferencePrior,
    reconstructions: Sequence[PropFeatures] = (),
    consistency_population: Sequence[float] = (),
    escalate_width: float | None = None,
    plausibility_weight: float = 0.5,
) -> TwoSidedVerdict:
    """Judge a prop on both sides, and say whether it is ambiguous.

    ``consistency`` is the caller's consistency score for this prop (the
    repair's silhouette IoU, or anything else on [0, 1]).
    ``consistency_population`` is the same score over the approved set —
    with it, the consistency side is put on the approved set's scale too,
    and the scale gap that was closed is measured. Without it, the
    consistency side is used raw and the gap is reported as zero, because
    an unmeasured gap is not a small gap.
    ``reconstructions`` are the night's other seeds for the same request.
    Give two or more and the ambiguity gate has something to say.
    """
    if not 0.0 <= plausibility_weight <= 1.0:
        raise ValueError("plausibility_weight is a share in [0, 1]")

    plausibility = prior.score(features)
    gap = prior.consistency_gap(consistency_population)

    if consistency_population:
        consistency_side = percentile_against(
            float(consistency), list(consistency_population)
        )
    else:
        consistency_side = float(consistency)

    # Both sides are on the approved set's scale, and the combination is a
    # weighted geometric mean: a prop that is perfect on one side and
    # impossible on the other does not average out.
    weight = float(plausibility_weight)
    combined = float(
        np.power(max(consistency_side, 1e-12), 1.0 - weight)
        * np.power(max(plausibility.score, 1e-12), weight)
    )

    width = fiber_width(reconstructions, prior)
    threshold = prior.ordinary_width if escalate_width is None else escalate_width
    ambiguous = bool(
        np.isfinite(width) and threshold > 0.0 and width > threshold
    )

    reasons: list[str] = []
    if ambiguous:
        reasons.append(
            f"the reconstructions disagree by {width:.3f}, more than real "
            f"objects of one kind do ({threshold:.3f}): the image did not "
            "determine the shape"
        )
    if plausibility.score < 0.2:
        reasons.append(
            f"the prop is less ordinary than {plausibility.score:.0%} of the "
            "approved objects of its kind"
        )

    return TwoSidedVerdict(
        consistency=float(consistency),
        plausibility=plausibility.score,
        combined=combined,
        ambiguous=ambiguous,
        escalate=ambiguous,
        reason="; ".join(reasons),
        gap=gap,
    )
