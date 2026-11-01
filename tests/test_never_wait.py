"""The "never wait" conductor (idea5 E1): a deadline, a fallback, and a supersede that never rewrites history."""
import asyncio
import importlib.util
import pathlib

_SRC = pathlib.Path(__file__).resolve().parents[1] / "docs/lab/never-wait-scripts/never_wait.py"
_spec = importlib.util.spec_from_file_location("never_wait", _SRC)
never_wait = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(never_wait)


async def _sleep_then(value, seconds):
    await asyncio.sleep(seconds)
    return value


def test_a_fast_worker_is_committed():
    async def run():
        c = never_wait.Conductor()
        got = await c.submit("r1", _sleep_then("real", 0.0), "fallback", 0.05)
        return got, c.history(), c.supersedes()

    got, history, supersedes = asyncio.run(run())
    assert got == "real"
    assert history == ["real"]
    assert supersedes == []


def test_a_slow_worker_commits_the_fallback_and_later_supersedes_it():
    async def run():
        c = never_wait.Conductor()
        got = await c.submit("r2", _sleep_then("late", 0.10), "fallback", 0.02)
        await asyncio.sleep(0.15)  # let the late worker finish
        return got, c.history(), c.supersedes()

    got, history, supersedes = asyncio.run(run())
    assert got == "fallback"
    assert history == ["fallback"]
    assert len(supersedes) == 1
    assert supersedes[0]["late_value"] == "late" and supersedes[0]["fallback"] == "fallback"


def test_history_never_changes_after_a_supersede():
    async def run():
        c = never_wait.Conductor()
        await c.submit("r3", _sleep_then("late", 0.05), "fallback", 0.01)
        before = c.history()
        await asyncio.sleep(0.10)
        return before, c.history(), c.supersedes()

    before, after, supersedes = asyncio.run(run())
    assert before == after == ["fallback"]
    assert len(supersedes) == 1


# The full 1,000-request experiment is the script itself (about 40 s):
#   python docs/lab/never-wait-scripts/never_wait.py   ->   PASS
