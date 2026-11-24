"""The skill library: content addressed, versioned, never deleted.

The rules are the tiles' rules (``docs/design/tiles.md`` §2), with the
world's own words:

1. **Content addressing.** A skill's id is ``skill_<12 hex>`` over its
   body. The same script written twice is the same skill: adding it again
   is a no-op, not a second version.
2. **Versioning.** A skill belongs to a **family** — what it is for. A new
   body in a family is the next version of that family. The library
   assigns the version; the author does not get to claim it.
3. **No deletion.** ``delete`` is refused, always. A skill leaves the
   eligible set by being **retired**: status, reason, timestamp. Its body,
   its plays and its history stay.
4. **Retirement is auditable.** The retirement is written to the log with
   the reason.

The library is on disk (one file per skill) because the world keeps
going when nobody is watching, and a restart must lose nothing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .door import check_body
from .models import (
    Precondition,
    Prediction,
    Skill,
    SkillAuthor,
    SkillKind,
    SkillRefusal,
    canonical_bytes,
    content_id,
    now_utc,
)

__all__ = ["SkillLibrary", "SkillBody", "build_skill"]


class SkillBody(dict):
    """The body of a skill: the parts that are hashed into its id."""

    family: str
    kind: SkillKind
    role: str
    title: str
    body: str
    api: tuple[str, ...]
    preconditions: tuple[Precondition, ...]
    predict: Prediction


def build_skill(
    *,
    family: str,
    role: str,
    title: str,
    body: str,
    author: SkillAuthor,
    kind: SkillKind = "behaviour",
    preconditions: Iterable[Mapping[str, Any]] = (),
    predict: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    node: str | None = None,
) -> Skill:
    """Build a skill and hold it to the door.

    This is the only way into the library. The body is checked against the
    vocabulary, the id is computed over the canonical body, and the
    version is left to the library.
    """
    api = check_body(body, node=node)
    hashed = {
        "family": family,
        "kind": kind,
        "role": role,
        "title": title,
        "body": body,
        "api": list(api),
        "preconditions": [dict(p) for p in preconditions],
        "predict": dict(predict or {"kind": "none"}),
    }
    return Skill(
        id=content_id(hashed),
        family=family,
        version=1,  # the library assigns the real one
        kind=kind,
        role=role,
        title=title,
        body=body,
        api=api,
        preconditions=tuple(Precondition(**p) for p in preconditions),
        predict=Prediction(**(predict or {"kind": "none"})),
        author=author,
        provenance=dict(provenance or {}),
    )


class SkillLibrary:
    """The options: a content-addressed store of immutable skills.

    One rule is the library's own: **the latest version of a family is
    the live one.** When a new version of a family is admitted, the
    older versions of that family are retired — not deleted. They keep
    their bodies, their plays and their history, and the log says when
    they were superseded and by what. That is what makes a family a
    family: it is one job, with attempts at it.
    """

    def __init__(self, root: Path | str, *, on_retire=None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, Skill] = {}
        self._on_retire = on_retire
        self._load()

    # -- the disk -------------------------------------------------------------

    def _load(self) -> None:
        for path in sorted(self.root.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            try:
                skill = Skill(**raw)
            except Exception:
                continue
            self._skills[skill.id] = skill

    def _write(self, skill: Skill) -> None:
        path = self.root / f"{skill.id}.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_bytes(canonical_bytes(skill.model_dump(mode="json")))
        tmp.replace(path)

    # -- the reads ------------------------------------------------------------

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def require(self, skill_id: str) -> Skill:
        skill = self._skills.get(skill_id)
        if skill is None:
            raise SkillRefusal("unknown_skill", f"no skill with id {skill_id}")
        return skill

    def all(self) -> tuple[Skill, ...]:
        return tuple(sorted(self._skills.values(), key=lambda s: (s.family, s.version, s.id)))

    def active(self) -> tuple[Skill, ...]:
        return tuple(s for s in self.all() if s.status == "active")

    def families(self) -> tuple[str, ...]:
        return tuple(sorted({s.family for s in self._skills.values()}))

    def versions(self, family: str) -> tuple[Skill, ...]:
        return tuple(s for s in self.all() if s.family == family)

    def eligible(
        self,
        context: Mapping[str, Any],
        *,
        role: str | None = None,
        limit: int | None = None,
    ) -> tuple[Skill, ...]:
        """The options that apply here.

        A skill that cannot apply in this context is not an option, and a
        context with no eligible skill is a refusal with a named reason —
        never a fallback to some other skill.
        """
        out = [
            s
            for s in self.active()
            if (role is None or s.role == role) and s.is_eligible(dict(context))
        ]
        if limit is not None:
            out = out[:limit]
        return tuple(out)

    # -- the writes -----------------------------------------------------------

    def add(self, skill: Skill) -> Skill:
        """Admit a skill. The same body twice is a no-op."""
        existing = self._skills.get(skill.id)
        if existing is not None:
            return existing
        version = self._next_version(skill.family)
        admitted = skill.model_copy(update={"version": version})
        self._skills[admitted.id] = admitted
        self._write(admitted)
        for retired in self.retire_superseded(admitted):
            if self._on_retire is not None:
                self._on_retire(retired, retired.retire_reason or "superseded")
        return admitted

    def sweep(self) -> list[Skill]:
        """Retire every version of a family that is not its latest.

        The library reconciles itself: whatever was admitted out of
        order, the rule holds after the sweep — the latest version of a
        family is the live one and the earlier attempts are retired,
        with the reason on the record.
        """
        out: list[Skill] = []
        for family in self.families():
            versions = self.versions(family)
            if not versions:
                continue
            latest = max(versions, key=lambda s: (s.version, s.id))
            for other in versions:
                if other.id == latest.id or other.status != "active":
                    continue
                retired = self.retire(
                    other.id,
                    reason=f"superseded by {latest.id} (version {latest.version} of {family})",
                )
                out.append(retired)
                if self._on_retire is not None:
                    self._on_retire(retired, retired.retire_reason or "superseded")
        return out

    def retire_superseded(self, skill: Skill) -> list[Skill]:
        """Retire the older versions of this family.

        The latest version of a family is the live one; the earlier
        attempts stay in the library and in the log.
        """
        out: list[Skill] = []
        for other in self.versions(skill.family):
            if other.id == skill.id or other.status != "active":
                continue
            out.append(
                self.retire(
                    other.id,
                    reason=f"superseded by {skill.id} (version {skill.version} of {skill.family})",
                )
            )
        return out

    def retire(self, skill_id: str, *, reason: str) -> Skill:
        """Retire a skill. It keeps its body, its plays and its history."""
        skill = self.require(skill_id)
        if skill.status == "retired":
            return skill
        retired = skill.model_copy(
            update={
                "status": "retired",
                "retired_at": now_utc(),
                "retire_reason": reason,
            }
        )
        self._skills[skill_id] = retired
        self._write(retired)
        return retired

    def delete(self, skill_id: str) -> None:
        """Refused, always. A skill is retired; it is never deleted."""
        raise SkillRefusal(
            "skills_are_never_deleted",
            "retire the skill instead; its body and its plays are the record",
        )

    def _next_version(self, family: str) -> int:
        versions = [s.version for s in self._skills.values() if s.family == family]
        return (max(versions) + 1) if versions else 1
