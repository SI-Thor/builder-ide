"""The probe's custom node — a loader, and one node that does nothing.

ComfyUI loads this from the base directory the probe's launcher points at,
so the TRELLIS.2 checkout is never touched.  The node exists only because
ComfyUI wants a custom node to declare its mappings; the work is done by
the probe itself, which this module installs.
"""

from __future__ import annotations

import os
import sys
import traceback

# The probe lives one level up from this package's parent directory.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

try:
    import probe  # noqa: E402  — the path is set up above

    probe.install()
except Exception:  # noqa: BLE001 — a probe that cannot load must not kill ComfyUI
    _out = os.environ.get("TRG_OUT", "/tmp/trg-probe.json")
    try:
        with open(_out + ".install-error", "w") as fh:
            fh.write(traceback.format_exc())
    except OSError:
        pass


class TRGProbeNode:
    """A node that does nothing, so the probe's package is a valid node."""

    @classmethod
    def INPUT_TYPES(cls):  # noqa: N802 — ComfyUI's own spelling
        return {"required": {}}

    RETURN_TYPES = ("TRIGGER",)
    RETURN_NAMES = ("trigger",)
    FUNCTION = "trigger"
    CATEGORY = "trg/probe"

    def trigger(self):
        return (True,)


NODE_CLASS_MAPPINGS = {"TRGProbeNode": TRGProbeNode}
NODE_DISPLAY_NAME_MAPPINGS = {"TRGProbeNode": "TRG Probe (no-op)"}
