"""Which critic scores the reference set — the parameter, the default, the fallback.

The critic used to be *always* the scripted checks, so there was nothing to
choose. The bake-off in ``docs/lab/exp-critic-select.md`` measured the
candidates against the same reference set and the same counting rule, and this
module is where the choice lives: a **parameter with a default**, and the
scripted checks as the **fallback** for everything.

Three rules:

1. **The default is the scripted critic.** It needs no model, no GPU and no
   network, it is the row every model candidate has to beat, and it is what
   the nightly re-score falls back to.
2. **A critic that cannot be built is not a crash.** The registry's
   ``build`` may fail — no torch, no VLM on the box, no API key — and then
   the fallback answers, with the reason attached to the verdict
   (``degraded``). A night that cannot reach its model still gets a table.
3. **The name is on the verdict's face.** ``verdict@scripted``,
   ``verdict@hybrid``, ``verdict@jev``: a reader always knows which critic
   made a verdict, and the published table always says which rows are the
   measured critic and which are the baseline.

The candidates that need a model are imported **lazily**, inside their
``build``: the core has no torch dependency and must not grow one, so
``import core.critic`` never needs the model stack to be installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence

from .critic import ReferenceCritic, ScriptedReferenceCritic

__all__ = [
    "CRITIC_DEFAULT",
    "SCRIPTED_OUT_OF_BAND",
    "CriticSpec",
    "CANDIDATES",
    "FallbackCritic",
    "candidate_names",
    "build_critic",
    "configured_critic",
    "configured_name",
    "resolve_critic",
]

#: The critic the core uses when nobody has chosen one: the scripted checks
#: in this package. They are the fallback for every candidate, and the
#: baseline row in the published table.
CRITIC_DEFAULT = "scripted"

#: The defect classes the scripted critic is **out of band** on, as the
#: published table measures it: ``floating_object`` (one miss of two
#: members, 50 % FN). The hybrid hands exactly these classes to a model and
#: leaves every other class to the checks.
#:
#: This is a *measurement*, not a preference, and it is the reason the
#: hybrid exists: the checks hold the band on eight of the nine classes, so
#: the only thing a model has to add is the ninth.
SCRIPTED_OUT_OF_BAND: tuple[str, ...] = ("floating_object",)


@dataclass(frozen=True)
class CriticSpec:
    """One candidate: what it is called, what it can see, how to build it.

    ``layers`` is the honest part. A critic that reads pixels cannot judge a
    defect that lives in the geometry, and the reference set's mesh defects
    are never re-rendered — so a pixel critic is measured on the image layer
    only, and says so, instead of being charged with misses it had no way to
    see.

    ``takes_classes`` says the candidate can be asked about a **subset** of
    the classes. The hybrid uses it: the delegate is only asked about the
    class the checks are out of band on, which is the difference between one
    model call per frame and six.
    """

    name: str
    layers: tuple[str, ...]
    summary: str
    build: Callable[..., ReferenceCritic]
    takes_classes: bool = False


def _build_scripted(**_: Any) -> ReferenceCritic:
    return ScriptedReferenceCritic()


def _build_dino_probe(**kwargs: Any) -> ReferenceCritic:
    from .candidates.dino import DinoProbeCritic

    return DinoProbeCritic(**kwargs)


def _build_vlm(**kwargs: Any) -> ReferenceCritic:
    from .candidates.vlm import VLMCritic

    return VLMCritic(**kwargs)


def _build_jev(**kwargs: Any) -> ReferenceCritic:
    from .candidates.jev import JevCritic

    return JevCritic(**kwargs)


def _build_hybrid(**kwargs: Any) -> ReferenceCritic:
    from .hybrid import HybridCritic

    delegate_name = kwargs.pop("delegate", "vlm")
    escalate = kwargs.pop("escalate", None)
    if escalate is None:
        escalate = SCRIPTED_OUT_OF_BAND
    escalate = tuple(escalate)
    spec = _spec_for(delegate_name)
    delegate_kwargs = dict(kwargs)
    if spec is not None and spec.takes_classes:
        # The delegate is only asked about the classes the checks cannot
        # answer for: one model call per frame instead of six.
        delegate_kwargs["classes"] = escalate
    delegate = build_critic(delegate_name, **delegate_kwargs)
    return HybridCritic(delegate, escalate=escalate)


#: Every candidate the selection knows about. The registry is data: the
#: default, the fallback and the hybrid's delegate are all names in it.
CANDIDATES: tuple[CriticSpec, ...] = (
    CriticSpec(
        name="scripted",
        layers=("image", "mesh"),
        summary="the scripted checks — analytic measurements, no model (the baseline)",
        build=_build_scripted,
    ),
    CriticSpec(
        name="dino-probe",
        layers=("image",),
        summary="DINOv2-large features with a per-class probe (local weights, GPU)",
        build=_build_dino_probe,
    ),
    CriticSpec(
        name="vlm",
        layers=("image",),
        summary="a local vision-language model asked one fixed yes/no question per class",
        build=_build_vlm,
        takes_classes=True,
    ),
    CriticSpec(
        name="jev",
        layers=("image",),
        summary="Jev in the cloud, over a text description of the frame and its measurements",
        build=_build_jev,
    ),
    CriticSpec(
        name="hybrid",
        layers=("image", "mesh"),
        summary="the scripted checks first, the model only where the checks are out of band",
        build=_build_hybrid,
    ),
)


def candidate_names() -> tuple[str, ...]:
    """The names the parameter accepts."""
    return tuple(spec.name for spec in CANDIDATES)


def _spec_for(name: str) -> CriticSpec | None:
    for spec in CANDIDATES:
        if spec.name == name:
            return spec
    return None


def build_critic(name: str | None = None, **kwargs: Any) -> ReferenceCritic:
    """Build the named critic.

    An unknown name, or a candidate whose dependencies are not on the box,
    raises :class:`CriticUnavailable` — the caller decides what to do with
    it (the fallback does), rather than this function quietly answering with
    a different critic than the one that was asked for.
    """
    wanted = name or CRITIC_DEFAULT
    spec = _spec_for(wanted)
    if spec is None:
        raise CriticUnavailable(
            f"no critic named {wanted!r}; the choices are {', '.join(candidate_names())}"
        )
    try:
        return spec.build(**kwargs)
    except CriticUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure is "unavailable"
        raise CriticUnavailable(
            f"the {wanted!r} critic could not be built: {exc}"
        ) from exc


def resolve_critic(
    name: str | None = None,
    **kwargs: Any,
) -> tuple[ReferenceCritic, str | None]:
    """The critic to use, and the reason it was not the one asked for.

    The fallback rule in one place: the scripted critic answers when the
    chosen one cannot be built, and the second element of the pair says
    why. The nightly re-score prints it; the published table carries it.

    A critic that cannot be **built** is one kind of failure. A critic
    that cannot **answer** — the VLM's server is down, the cloud critic's
    key has expired, the probe's weights are gone — is the other kind, and
    it happens one member at a time, at score time. The chosen critic is
    therefore wrapped: the checks answer that member and the verdict says
    which critic actually made it.
    """
    wanted = name or CRITIC_DEFAULT
    if wanted == CRITIC_DEFAULT:
        return ScriptedReferenceCritic(), None
    try:
        return FallbackCritic(build_critic(wanted, **kwargs)), None
    except CriticUnavailable as exc:
        return ScriptedReferenceCritic(), str(exc)


class FallbackCritic:
    """The chosen critic, with the scripted checks behind it.

    The checks are the fallback for **both** ways a candidate can fail: it
    cannot be built (handled by :func:`resolve_critic`), and it cannot
    answer (handled here). The second is the one that happens at night: a
    model server that is not resident, a key that has expired, a set of
    weights that has gone missing. A night that hits it still gets a table,
    and the verdict says on its face that the model did not answer.
    """

    def __init__(self, critic: ReferenceCritic) -> None:
        self._critic = critic
        self._scripted = ScriptedReferenceCritic()

    @property
    def critic(self) -> ReferenceCritic:
        """The critic that was asked for."""
        return self._critic

    @property
    def name(self) -> str:
        return self._critic.name

    @property
    def layers(self) -> tuple[str, ...]:
        return self._critic.layers

    def score(
        self,
        member: Any,
        *,
        bases: Sequence[Any] = (),
        thresholds: Any = None,
        cache_dir: str | None = None,
        blender_python: str | None = None,
    ) -> Any:
        """The chosen critic's verdict, or the checks' when it cannot answer."""
        try:
            return self._critic.score(
                member,
                bases=bases,
                thresholds=thresholds,
                cache_dir=cache_dir,
            )
        except Exception as exc:  # noqa: BLE001 - any failure is a fallback
            verdict = self._scripted.score(
                member,
                bases=bases,
                thresholds=thresholds,
                cache_dir=cache_dir,
            )
            reason = (
                f"the {self._critic.name} critic could not answer "
                f"({type(exc).__name__}: {exc}) — the scripted checks answered"
            )
            return replace(
                verdict,
                checks=tuple(
                    replace(c, detail=f"{c.detail} — {reason}")
                    for c in verdict.checks
                ),
                label=f"verdict@{self._critic.name}",
                degraded="scripted",
            )


class CriticUnavailable(RuntimeError):
    """The named critic cannot be built on this box."""


# -- the configured critic ----------------------------------------------------


def configured_name(settings: Any = None) -> str:
    """The name of the critic this box is configured to use.

    One place, so the nightly re-score and the night runner cannot disagree
    about which critic is in service. The order is: the **settings** (which
    the config already reads from ``BUILDER_CRITIC``), then the environment
    directly, and then the default — the scripted checks.
    """
    name = getattr(settings, "critic", None)
    if name:
        return str(name)
    env = os.environ.get("BUILDER_CRITIC")
    return env or CRITIC_DEFAULT


def configured_critic(
    settings: Any = None,
    **kwargs: Any,
) -> tuple[ReferenceCritic, str | None]:
    """The configured critic, and the reason it is not the one asked for.

    The same fallback rule as :func:`resolve_critic`: the scripted checks
    answer whenever the chosen critic cannot be built, and the reason travels
    with the verdict.
    """
    return resolve_critic(configured_name(settings), **kwargs)
