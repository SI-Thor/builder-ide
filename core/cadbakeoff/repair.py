"""The one repair round.

Hy4 guard 2: a repair may fix the code, not the design. So the brief is
repeated verbatim, the error is given in a kernel-agnostic shape
(``{"stage": ..., "message": ...}``), and the repair is checked against the
same frozen spec afterwards. A repair that moved a parameter, a cell or a
joint is recorded as ``design_changed`` and is left out of the after-repair
rate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from core.cadbakeoff.prompts import FORMAT_BUILD123D, FORMAT_SOLIDCRAFT, EXAMPLE_BUILD123D, EXAMPLE_SOLIDCRAFT, RULES, render_prop_brief
from core.cadbakeoff.specs import PROPS

__all__ = [
    "RepairRequest",
    "build_repair_prompt",
    "declared_parameters",
    "design_changed",
    "spec_diff",
]


@dataclass
class RepairRequest:
    prop: str
    kernel: str
    stage: str
    message: str
    artifact: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "prop": self.prop,
            "kernel": self.kernel,
            "stage": self.stage,
            "message": self.message,
            "artifact": self.artifact,
        }


def build_repair_prompt(request: RepairRequest, previous: str) -> str:
    """The same prompt as the first attempt, plus the error and the fix rule."""
    spec = PROPS[request.prop]
    fmt = FORMAT_SOLIDCRAFT if request.kernel == "solidcraft" else FORMAT_BUILD123D
    example = EXAMPLE_SOLIDCRAFT if request.kernel == "solidcraft" else EXAMPLE_BUILD123D
    error = json.dumps({"stage": request.stage, "message": request.message}, indent=1)
    return "\n".join(
        [
            "You are a mechanical CAD prop designer. You write one script that",
            "builds one prop: a parametric rigid-body assembly for a physics",
            "simulation.",
            "",
            render_prop_brief(spec),
            "",
            RULES,
            "",
            fmt,
            "",
            example,
            "",
            "=== REPAIR ===",
            "The script below did not build. This is the error, as a stage and a",
            "message:",
            "",
            error,
            "",
            "Write the whole script again, with the fix in it. Keep the design",
            "exactly as the brief says: the same parameter names with the same",
            "values, the same bodies and cells, the same joint and limits, the",
            "same action. Change only the code. Do not shrink a dimension, do not",
            "move a joint, do not lower a limit to make the error go away.",
            "",
            "The script that failed:",
            "",
            previous,
        ]
    )


# ---------------------------------------------------------------------------
# what the script says its parameters are
# ---------------------------------------------------------------------------

_SOLIDCRAFT_PARAM = re.compile(
    r'"command"\s*:\s*"parameters\.add".*?"params"\s*:\s*(\{.*?\})\s*\}', re.DOTALL
)


def declared_parameters(kernel: str, artifact: str) -> dict[str, float] | None:
    """The parameter values the script declares, as a dict."""
    if kernel == "solidcraft":
        try:
            payload = json.loads(artifact)
        except json.JSONDecodeError:
            return None
        out: dict[str, float] = {}
        for entry in payload.get("commands", []):
            if not isinstance(entry, dict) or entry.get("command") != "parameters.add":
                continue
            params = entry.get("params") or {}
            name = params.get("name")
            expression = params.get("expression")
            if not isinstance(name, str) or expression is None:
                continue
            try:
                out[name] = float(str(expression).split()[0])
            except (TypeError, ValueError):
                return None
        return out
    # build123d: the PARAMS dict literal.
    match = re.search(r"^PARAMS\s*=\s*\{(.*?)\}", artifact, re.DOTALL | re.MULTILINE)
    if not match:
        return None
    out = {}
    for name, value in re.findall(r"[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*:\s*(-?[0-9.]+)", match.group(1)):
        out[name] = float(value)
    return out or None


def design_changed(kernel: str, artifact: str, prop: str) -> bool:
    """Did the repair move the design? Compared against the frozen spec."""
    spec = PROPS[prop]
    declared = declared_parameters(kernel, artifact)
    if declared is None:
        return False  # cannot tell; the URDF check will catch a moved design
    wanted = spec["parameters"]
    if set(declared) != set(wanted):
        return True
    for name, value in wanted.items():
        if abs(declared[name] - value) > 1e-6:
            return True
    return False


def spec_diff(kernel: str, artifact: str, prop: str) -> dict[str, Any]:
    """What the artefact says against the frozen spec, in a form to log.

    The parameters are the ones a repair can shrink to make an error go
    away, so they are compared name by name. The joint limits are compared
    too, on the SolidCraft side, where the script states them; on the
    build123d side the limits only reach the URDF, and the URDF check
    catches them there.
    """
    spec = PROPS[prop]
    wanted = dict(spec["parameters"])
    declared = declared_parameters(kernel, artifact)
    diff: dict[str, Any] = {
        "parameters": {},
        "parameters_missing": [],
        "parameters_added": [],
        "joint_limits": {},
    }
    if declared is None:
        diff["parameters_unreadable"] = True
    else:
        for name, value in wanted.items():
            if name not in declared:
                diff["parameters_missing"].append(name)
            elif abs(declared[name] - value) > 1e-6:
                diff["parameters"][name] = {"spec": value, "artifact": declared[name]}
        for name in declared:
            if name not in wanted:
                diff["parameters_added"].append(name)

    if kernel == "solidcraft":
        try:
            payload = json.loads(artifact)
        except json.JSONDecodeError:
            payload = {}
        for entry in payload.get("commands", []):
            if not isinstance(entry, dict) or entry.get("command") != "joint.create":
                continue
            params = entry.get("params") or {}
            name = params.get("name")
            limits = params.get("limits")
            if name is None or not isinstance(limits, (list, tuple)) or len(limits) != 2:
                continue
            want = None
            for joint in spec["joints"]:
                if joint["name"] == name:
                    want = joint["limits"]
                    break
            if want is None:
                diff["joint_limits"][name] = {"spec": None, "artifact": list(limits)}
            elif [float(limits[0]), float(limits[1])] != [float(want[0]), float(want[1])]:
                diff["joint_limits"][name] = {"spec": list(want), "artifact": list(limits)}
    return diff
