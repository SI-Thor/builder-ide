#!/usr/bin/env python3
"""test_seatwatch.py: the watcher's tests.

The fixtures are the lab's own recorded day (``docs/lab/seat-watcher/data``),
because that is the only record of a day of real stalls that exists.  The
headline test replays it and checks that the live engine and the lab's own
gates give the same answer, speech for speech.

    python3 tools/seat-watch/test_seatwatch.py           # everything
    python3 tools/seat-watch/test_seatwatch.py -v        # with names

The replay test takes about 15 seconds (it walks 16 hours of the day one
second at a time, six gates).  The rest are fast.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
LAB = os.path.join(ROOT, "docs", "lab", "seat-watcher")

sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(LAB, "scripts"))

import seatwatch  # noqa: E402
from seatwatch import (DEFAULTS, Engine, Latch, SeatState, TrailingSlope,  # noqa: E402
                        Watcher)


def make_watcher(params=None, **kw):
    """A watcher with the knobs the tests need, and no boxes to read."""
    p = dict(DEFAULTS)
    if params:
        p.update(params)
    cfg = {"params": p, "ssh": "thor-lan", "ssh_timeout": 5,
           "ops": "/tmp", "log": "/tmp/seat-watch-test.log", "timeout": 0,
           "started_at": 0.0}
    cfg.update(kw)
    return Watcher(cfg)


def job(name, exits=0, quota=False, mtime=0.0, size=10, live=True,
        cpu=0.0, net=0, notes=None, git=None, ssh=None, counter=None):
    """One job's facts, in the shape the collector returns."""
    out = {"size": size, "mtime": mtime, "exits": exits, "quota": quota,
           "counter": counter}
    return {"kind": "job", "machine": "proart", "t": mtime, "name": name,
            "out": out, "notes": notes, "git": git, "pane": 1 if live else 0,
            "cpu": cpu, "net": net, "ssh": ssh or [], "live": live}


# ---------------------------------------------------------------------------
class TestLatch(unittest.TestCase):
    """The latch: it speaks on the rising edge, and only after the dwell."""

    def test_dwell_before_speaking(self):
        lat = Latch(hold=30)
        self.assertFalse(lat.update(True, 100))
        self.assertFalse(lat.update(True, 129))
        self.assertTrue(lat.update(True, 130))     # 30 s after it started

    def test_one_speech_while_it_holds(self):
        lat = Latch(hold=30)
        lat.update(True, 100)
        self.assertTrue(lat.update(True, 130))
        for t in (131, 200, 1000):
            self.assertFalse(lat.update(True, t))

    def test_re_arms_when_it_clears(self):
        lat = Latch(hold=0)
        self.assertTrue(lat.update(True, 100))
        self.assertFalse(lat.update(True, 101))
        lat.update(False, 102)
        self.assertTrue(lat.update(True, 103))


# ---------------------------------------------------------------------------
class TestTrailingSlope(unittest.TestCase):
    """The lab's two rules: the window is contiguous, and it has to span."""

    def test_slope_over_a_contiguous_window(self):
        s = TrailingSlope(600, 30, 60, scale=1e9, unit_s=60)
        for i in range(7):
            s.add(1000 + i * 10, (100 - i * 2) * 1e9)
        # 12 GB over 60 s = 12 GB/min
        self.assertAlmostEqual(s.slope(1060), -12.0, places=6)

    def test_no_rate_across_a_gap(self):
        """The box going down must not be read as a rate."""
        s = TrailingSlope(600, 30, 60, scale=1e9, unit_s=60)
        s.add(1000, 100e9)
        s.add(1010, 100e9)
        s.add(1100, 40e9)        # a 90 s gap: the daemon restarted
        # the walk stops at the gap, so the window is only 10 s wide
        self.assertIsNone(s.slope(1100))

    def test_no_rate_below_the_minimum_span(self):
        s = TrailingSlope(600, 30, 60, scale=1e9, unit_s=60)
        s.add(1000, 100e9)
        s.add(1010, 90e9)
        self.assertIsNone(s.slope(1010))     # a 10 s window is not a rate

    def test_the_base_sample_is_in_the_series(self):
        """When the newest sample is older than the query time, the base counts.

        This is the case the lab's day contains: the box goes quiet and the
        slope is measured over the base and the samples inside the window.
        """
        s = TrailingSlope(600, 30, 60, scale=1e9, unit_s=60)
        for i in range(7):
            s.add(1000 + i * 10, (100 - i * 2) * 1e9)
        # the query is 300 s after the last sample: the base is inside the
        # window measured from the newest sample, so it is the oldest sample
        self.assertAlmostEqual(s.slope(1360), -12.0, places=6)


# ---------------------------------------------------------------------------
class TestDoneRule(unittest.TestCase):
    """watch-all.sh's rule: the EXIT markers present at the start do not count."""

    def test_a_marker_present_at_the_start_is_ignored(self):
        w = make_watcher()
        jobs = {("proart", "a"): job("a", exits=1, mtime=10)}
        w.baseline(jobs)
        self.assertIsNone(w.check_done(jobs))

    def test_a_new_marker_is_reported(self):
        w = make_watcher()
        jobs = {("proart", "a"): job("a", exits=1, mtime=10)}
        w.baseline(jobs)
        jobs[("proart", "a")] = job("a", exits=2, mtime=20)
        self.assertEqual(w.check_done(jobs), "DONE proart a")

    def test_a_new_file_counts_from_zero(self):
        w = make_watcher()
        w.baseline({})
        jobs = {("thor", "new"): job("new", exits=1, mtime=20)}
        self.assertEqual(w.check_done(jobs), "DONE thor new")


# ---------------------------------------------------------------------------
class TestQuotaRule(unittest.TestCase):
    """Old .out files keep their quota markers; a stale one must not be read."""

    def test_a_stale_marker_is_not_reported(self):
        w = make_watcher()
        jobs = {("proart", "old"): job("old", quota=True, mtime=100)}
        w.baseline(jobs)
        self.assertIsNone(w.check_quota(jobs))

    def test_a_new_marker_is_reported(self):
        w = make_watcher()
        jobs = {("proart", "old"): job("old", quota=False, mtime=100)}
        w.baseline(jobs)
        jobs[("proart", "old")] = job("old", quota=True, mtime=200)
        self.assertEqual(w.check_quota(jobs), "QUOTA old")

    def test_a_marker_in_a_file_being_written_is_reported(self):
        w = make_watcher()
        jobs = {("proart", "old"): job("old", quota=True, mtime=100)}
        w.baseline(jobs)
        jobs[("proart", "old")] = job("old", quota=True, mtime=300)
        self.assertEqual(w.check_quota(jobs), "QUOTA old")


# ---------------------------------------------------------------------------
class TestStallGate(unittest.TestCase):
    """A seat that stops making progress."""

    def _watcher(self, window=600):
        w = make_watcher({"stall_window_s": window})
        w.cfg["out_ages"] = {}
        w.cfg["ssh_children"] = {}
        return w

    def test_a_silent_seat_is_stalled_after_the_window(self):
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "a"): job("a", mtime=t, size=100, cpu=1.0, net=10)}
        self.assertIsNone(w.check_stall(jobs, t))
        # still silent, but the window has not passed
        self.assertIsNone(w.check_stall(jobs, t + 599))
        self.assertEqual(w.check_stall(jobs, t + 600), "STALL a no_progress")

    def test_progress_resets_the_window(self):
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "a"): job("a", mtime=t, size=100, cpu=1.0, net=10)}
        w.check_stall(jobs, t)
        # the seat writes: the .out grows and the process burns CPU
        jobs[("proart", "a")] = job("a", mtime=t + 100, size=140, cpu=3.0, net=50)
        self.assertIsNone(w.check_stall(jobs, t + 100))
        # so the window starts again from the write
        self.assertIsNone(w.check_stall(jobs, t + 100 + 599))
        self.assertEqual(w.check_stall(jobs, t + 100 + 600), "STALL a no_progress")

    def test_a_new_commit_is_progress(self):
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "a"): job("a", mtime=t, size=100, cpu=1.0, net=10,
                                     git={"sha": "aaa", "ct": t})}
        w.check_stall(jobs, t)
        jobs[("proart", "a")] = job("a", mtime=t + 100, size=100, cpu=1.0, net=10,
                                    git={"sha": "bbb", "ct": t + 100})
        self.assertIsNone(w.check_stall(jobs, t + 100))

    def test_a_gap_in_the_evidence_restarts_the_window(self):
        """A poll that cannot read the job is not evidence of a stall."""
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "a"): job("a", mtime=t, size=100, cpu=1.0, net=10)}
        w.check_stall(jobs, t)
        # the job is not in this poll: the collector could not read it
        self.assertIsNone(w.check_stall({}, t + 700))
        # and it comes back, so the window starts again
        jobs[("proart", "a")] = job("a", mtime=t + 700, size=100, cpu=1.0, net=10)
        self.assertIsNone(w.check_stall(jobs, t + 700))
        self.assertIsNone(w.check_stall(jobs, t + 700 + 599))
        self.assertEqual(w.check_stall(jobs, t + 700 + 600), "STALL a no_progress")

    def test_it_speaks_once(self):
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "a"): job("a", mtime=t, size=100, cpu=1.0, net=10)}
        w.check_stall(jobs, t)
        self.assertEqual(w.check_stall(jobs, t + 600), "STALL a no_progress")
        self.assertIsNone(w.check_stall(jobs, t + 700))

    def test_a_seat_with_no_window_is_not_stalled(self):
        """The lab's lesson: 160 of the level gate's 181 alarms were on seats
        that had already exited.  A seat with no window is not a live seat."""
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "dead"): job("dead", mtime=t, size=100, live=False)}
        w.check_stall(jobs, t)
        self.assertIsNone(w.check_stall(jobs, t + 5000))

    def test_the_ssh_child_shape(self):
        """An ssh child alive > 30 min with no output."""
        w = self._watcher()
        t = 1000.0
        jobs = {("proart", "a"): job("a", mtime=t - 4000, size=100, cpu=1.0, net=10,
                                     ssh=[{"pid": 42, "age_s": 4000, "start": t - 4000}])}
        self.assertEqual(w.check_stall(jobs, t), "STALL a ssh_child_idle")

    def test_a_developing_ssh_shape_holds_the_generic_gate_back(self):
        """The generic gate would otherwise always win, and the reason would
        never say which shape it was."""
        w = self._watcher()
        t = 1000.0
        # the ssh is 20 min old (too young to be confirmed) and the output
        # stopped 20 min ago (past the generic window)
        jobs = {("proart", "a"): job("a", mtime=t - 1200, size=100, cpu=1.0, net=10,
                                     ssh=[{"pid": 42, "age_s": 1200, "start": t - 1200}])}
        self.assertIsNone(w.check_stall(jobs, t))
        # once the ssh is over 30 min old, the shape is named
        jobs[("proart", "a")] = job("a", mtime=t - 1900, size=100, cpu=1.0, net=10,
                                    ssh=[{"pid": 42, "age_s": 1900, "start": t - 1900}])
        self.assertEqual(w.check_stall(jobs, t + 10), "STALL a ssh_child_idle")

    def test_the_watcher_loop_shape(self):
        """A log that keeps saying nothing is running."""
        w = self._watcher()
        t = 1000.0
        counter = {"text": "c=0 t=0", "all_zero": True, "fields": 2}
        jobs = {("proart", "a"): job("a", mtime=t, size=100, counter=counter)}
        self.assertIsNone(w.check_stall(jobs, t))
        # the generic gate is held back while the loop shape develops
        self.assertIsNone(w.check_stall(jobs, t + 700))
        self.assertEqual(w.check_stall(jobs, t + 3601), "STALL a watcher_loop")

    def test_a_counter_line_with_work_in_it_is_not_a_loop(self):
        w = self._watcher()
        t = 1000.0
        counter = {"text": "c=3 t=1", "all_zero": False, "fields": 2}
        jobs = {("proart", "a"): job("a", mtime=t, size=100, counter=counter)}
        w.check_stall(jobs, t)
        # the counter line shows work in it, so the generic gate is not held
        # back and the seat is reported as a plain stall
        self.assertEqual(w.check_stall(jobs, t + 600), "STALL a no_progress")


# ---------------------------------------------------------------------------
class TestBoxConditions(unittest.TestCase):
    """The box's own state, over a series the way the live watcher feeds it."""

    def _run_box(self, samples, extra=None):
        """Feed a series and step at every sample, the way the live watcher does."""
        eng = Engine(DEFAULTS)
        seen = []
        for rec in samples:
            eng.feed(rec)
            seen.extend(e["cond"] for e in eng.step(rec["t"], which="live"))
        return seen

    def test_memory_falling_fast(self):
        t = 1000.0
        # 80 x 15 s = 20 min, losing 1 GB a step: 4 GB/min, over the 3 GB/min
        samples = [{"k": "box", "t": t + i * 15, "mem": int((100 - i) * 1e9)}
                   for i in range(80)]
        self.assertIn("memory_falling_fast", self._run_box(samples))

    def test_a_steady_box_says_nothing(self):
        t = 1000.0
        samples = [{"k": "box", "t": t + i * 15, "mem": int(100e9)}
                   for i in range(80)]
        self.assertNotIn("memory_falling_fast", self._run_box(samples))

    def test_the_disk_floor(self):
        t = 1000.0
        samples = [{"k": "disk", "t": t, "gb": 25.0},
                   {"k": "disk", "t": t + 60, "gb": 19.0},
                   {"k": "disk", "t": t + 120, "gb": 19.0}]
        self.assertIn("box_disk_low", self._run_box(samples))

    def test_the_box_going_dark(self):
        """The box stops answering: the collector fails, so no sample arrives.

        This is the live watcher's version of the lab's 15:50 outage, where
        the daemon's last sample was 2 min 39 s before it noticed.
        """
        t = 1000.0
        eng = Engine(DEFAULTS)
        eng.feed({"k": "box", "t": t, "mem": int(100e9)})
        conds = []
        for dt in (15, 60, 121, 160, 200):
            conds.extend(e["cond"] for e in eng.step(t + dt, which="live"))
        self.assertIn("telemetry_dark", conds)


# ---------------------------------------------------------------------------
class TestTheTwoBoxes(unittest.TestCase):
    """The Thor and the ProArt are separate channels, not one series.

    This is a regression test for a defect that was live in the first version
    of this watcher: the poll fed both boxes' records into one series, so the
    slope measured the *difference between the boxes* -- 804 GB of disk on the
    ProArt alternating with 85 GB on the Thor -- and read -21,504 GB/h of
    "disk falling" on a healthy pair of boxes.  The watcher would have cried
    BOX about two minutes after every start.
    """

    def _feed_both(self, eng, t0, n=9, mem_proart=8.8, mem_thor=93.0,
                   disk_proart=804.0, disk_thor=85.4, swap=0):
        for k in range(n):
            a = t0 + k * 15.0
            eng.feed({"k": "box", "t": a, "mem": int(mem_proart * 1e9),
                      "swap_used": int(swap * 1e9), "m": "proart"})
            eng.feed({"k": "box", "t": a + 0.3, "mem": int(mem_thor * 1e9),
                      "m": "thor"})
            eng.feed({"k": "disk", "t": a, "gb": disk_proart, "m": "proart"})
            eng.feed({"k": "disk", "t": a + 0.3, "gb": disk_thor, "m": "thor"})
        return t0 + (n - 1) * 15.0 + 0.3

    def test_the_thor_slope_is_the_thors_own(self):
        eng = Engine(DEFAULTS)
        t = self._feed_both(eng, 1000.0)
        self.assertAlmostEqual(eng.channel("thor").disk.slope(t), 0.0, places=6)
        self.assertAlmostEqual(eng.channel("thor").mem.slope(t), 0.0, places=6)

    def test_a_healthy_pair_of_boxes_says_nothing(self):
        eng = Engine(DEFAULTS)
        t = self._feed_both(eng, 1000.0)
        self.assertEqual([e["cond"] for e in eng.step(t, which="live")], [])

    def test_the_thors_disk_fall_is_still_caught(self):
        """Separating the boxes must not stop the Thor's own fall."""
        eng = Engine(DEFAULTS)
        t0 = 1000.0
        n = 80
        for k in range(n):
            a = t0 + k * 15.0
            eng.feed({"k": "box", "t": a, "mem": int(93e9), "m": "proart"})
            eng.feed({"k": "box", "t": a + 0.3, "mem": int(93e9), "m": "thor"})
            eng.feed({"k": "disk", "t": a, "gb": 804.0, "m": "proart"})
            eng.feed({"k": "disk", "t": a + 0.3, "gb": 200.0 - k * 2.0, "m": "thor"})
        conds = []
        t = t0
        for k in range(n):
            conds.extend(e["cond"] for e in eng.step(t0 + k * 15.0 + 0.3, which="live"))
        self.assertIn("disk_falling_fast", conds)

    def test_a_record_with_no_machine_is_the_thors(self):
        """The lab's recorded stream is the Thor's series, so it must land
        in the Thor's channel and reproduce the lab's numbers."""
        eng = Engine(DEFAULTS)
        eng.feed({"k": "box", "t": 1000.0, "mem": int(93e9)})
        self.assertEqual(list(eng.boxes), ["thor"])
        self.assertAlmostEqual(eng.channel("thor").mem.slope(1000.0) or 0.0, 0.0)


# ---------------------------------------------------------------------------
class TestProartMemory(unittest.TestCase):
    """The desk's MEM signal: the ProArt's own memory, on the ProArt."""

    def _run(self, samples):
        eng = Engine(DEFAULTS)
        conds = []
        for rec in samples:
            eng.feed(rec)
            conds.extend(e["cond"] for e in eng.step(rec["t"], which="live"))
        return conds

    def test_the_memory_floor(self):
        """MemAvailable under 2 GB on the ProArt."""
        t = 1000.0
        samples = [{"k": "box", "t": t + i * 15, "mem": int(1.5e9),
                    "swap_used": 0, "m": "proart"} for i in range(10)]
        self.assertIn("proart_memory_low", self._run(samples))

    def test_a_comfortable_proart_says_nothing(self):
        t = 1000.0
        samples = [{"k": "box", "t": t + i * 15, "mem": int(8.8e9),
                    "swap_used": 0, "m": "proart"} for i in range(40)]
        self.assertNotIn("proart_memory_low", self._run(samples))
        self.assertNotIn("proart_swap_rising", self._run(samples))

    def test_swap_in_use_and_rising(self):
        """The leading indicator: swap growing 0.4 GB a step (1.6 GB/min)."""
        t = 1000.0
        samples = [{"k": "box", "t": t + i * 15, "mem": int(6e9),
                    "swap_used": int(i * 0.4e9), "m": "proart"}
                   for i in range(40)]
        self.assertIn("proart_swap_rising", self._run(samples))

    def test_swap_in_use_but_steady_is_not_a_fire(self):
        """Swap that has settled is not a rising condition."""
        t = 1000.0
        samples = [{"k": "box", "t": t + i * 15, "mem": int(6e9),
                    "swap_used": int(2e9), "m": "proart"} for i in range(40)]
        self.assertNotIn("proart_swap_rising", self._run(samples))

    def test_the_reason_is_proart_memory(self):
        """Both conditions print the one reason the desk named."""
        from seatwatch import BOX_REASONS
        self.assertEqual(BOX_REASONS["proart_memory_low"], "proart-memory")
        self.assertEqual(BOX_REASONS["proart_swap_rising"], "proart-memory")

    def test_the_thors_memory_is_not_the_proarts(self):
        """A Thor with 1.5 GB free must not report the ProArt's memory."""
        t = 1000.0
        samples = [{"k": "box", "t": t + i * 15, "mem": int(1.5e9),
                    "m": "thor"} for i in range(10)]
        self.assertNotIn("proart_memory_low", self._run(samples))


# ---------------------------------------------------------------------------
class TestCollector(unittest.TestCase):
    """The collector that runs on both boxes."""

    def _run(self, files):
        tmp = tempfile.mkdtemp(prefix="seat-watch-test-")
        try:
            os.makedirs(os.path.join(tmp, "wt"))
            for name, text in files.items():
                with open(os.path.join(tmp, "wt", name), "w") as fh:
                    fh.write(text)
            env = dict(os.environ)
            env["LM_OPS"] = tmp
            out = subprocess.run([sys.executable, "-", "proart"],
                                 input=seatwatch.COLLECTOR_SRC, text=True,
                                 capture_output=True, env=env, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            recs = [json.loads(line) for line in out.stdout.splitlines() if line.strip()]
            return tmp, recs
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_exit_lines_are_counted(self):
        tmp, recs = self._run({"a.out": "some output\nEXIT 0\nmore\nEXIT 1\n"})
        jobs = [r for r in recs if r.get("kind") == "job"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["out"]["exits"], 2)

    def test_quota_markers_are_found(self):
        tmp, recs = self._run({
            "a.out": "Token Plan usage limit reached (2056)\n",
            "b.out": "Limit Exhausted\n",
            "c.out": "all fine\n",
        })
        jobs = {r["name"]: r for r in recs if r.get("kind") == "job"}
        self.assertTrue(jobs["a"]["out"]["quota"])
        self.assertTrue(jobs["b"]["out"]["quota"])
        self.assertFalse(jobs["c"]["out"]["quota"])

    def test_a_counter_line_is_found(self):
        tmp, recs = self._run({"a.out": "c=0 t=0\nc=0 t=0\n"})
        jobs = [r for r in recs if r.get("kind") == "job"]
        counter = jobs[0]["out"]["counter"]
        self.assertIsNotNone(counter)
        self.assertTrue(counter["all_zero"])

    def test_a_counter_line_with_work_is_not_all_zero(self):
        tmp, recs = self._run({"a.out": "c=3 t=1\n"})
        jobs = [r for r in recs if r.get("kind") == "job"]
        self.assertFalse(jobs[0]["out"]["counter"]["all_zero"])

    def test_the_box_is_reported(self):
        tmp, recs = self._run({"a.out": "x\n"})
        box = [r for r in recs if r.get("kind") == "box"]
        self.assertEqual(len(box), 1)
        self.assertIsNotNone(box[0]["mem"])
        self.assertIsNotNone(box[0]["disk_gb"])
        self.assertIsNotNone(box[0]["swap_used"])

    def test_the_swap_in_use_is_read(self):
        """The ProArt's swap is the MEM signal's leading indicator."""
        tmp, recs = self._run({"a.out": "x\n"})
        box = [r for r in recs if r.get("kind") == "box"][0]
        used = box["swap_used"]
        self.assertGreaterEqual(used, 0)
        with open("/proc/meminfo") as fh:
            info = dict(line.split(":") for line in fh
                        if line.startswith(("SwapTotal:", "SwapFree:")))
        total = int(info["SwapTotal"].split()[0]) * 1024
        free = int(info["SwapFree"].split()[0]) * 1024
        self.assertEqual(used, max(0, total - free))


# ---------------------------------------------------------------------------
class TestReplayMatchesTheLab(unittest.TestCase):
    """The headline test: the live engine and the lab's gates agree.

    This is the dry run the brief asks for.  The fixture is the lab's own
    recorded day (2026-11-01), the lab's own parameters, and the lab's own
    scorer: the replay's events are compared with the lab's committed events,
    and the lab's scorer is run on the replay's events and its numbers
    compared with the lab's RESULT.json.
    """

    @classmethod
    def setUpClass(cls):
        import common
        import replay
        cls.replay = replay
        rows = replay.load_stream(os.path.join(LAB, "data", "stream.jsonl"))
        cls.theirs = json.load(open(os.path.join(LAB, "data", "events.json")))
        cls.mine = replay.replay_gates(
            rows, (common.WINDOW_START, common.WINDOW_END),
            params=cls.theirs["params"])

    def test_the_lab_speeches_are_reproduced(self):
        for which in ("a", "b", "ab", "bplus", "a_live"):
            mine = self.replay.compare(
                self.mine[which], self.theirs["gates"][which]["events"])
            self.assertTrue(mine["same"],
                            "gate %s: %s" % (which, mine))
            self.assertEqual(mine["mine"], mine["theirs"])

    def test_the_rate_gate_speaks_71_times(self):
        self.assertEqual(len(self.mine["b"]), 71)
        self.assertEqual(len(self.mine["bplus"]), 77)
        self.assertEqual(len(self.mine["a"]), 184)
        self.assertEqual(len(self.mine["a_live"]), 24)

    def test_the_lab_scorer_gives_the_lab_s_numbers(self):
        import labels
        import score as score_mod
        episodes = sorted(labels.EPISODES, key=lambda e: e["t_help"])
        theirs = json.load(open(os.path.join(LAB, "RESULT.json")))
        for which in ("a", "b", "ab", "bplus", "a_live"):
            s = score_mod.score_gate(which, self.mine[which], episodes)["episode"]
            lab = theirs["gates"][which]["episode"]
            for k in ("speaks", "tp", "fp", "fn", "precision", "recall",
                      "false_positive_rate", "false_alarms_per_hour"):
                self.assertEqual(s[k], lab[k], "gate %s, %s" % (which, k))
            self.assertEqual(s["lead_minutes"], lab["lead_minutes"])
            self.assertEqual(s["stall_minutes_saved"], lab["stall_minutes_saved"])

    def test_the_rate_gate_catches_eight_of_thirteen(self):
        import labels
        import score as score_mod
        episodes = sorted(labels.EPISODES, key=lambda e: e["t_help"])
        s = score_mod.score_gate("b", self.mine["b"], episodes)["episode"]
        self.assertEqual(s["tp"], 8)
        self.assertEqual(s["recall"], 0.6154)
        self.assertEqual(s["lead_minutes"]["mean"], 50.3)
        self.assertEqual(s["stall_minutes_saved"]["total"], 385.3)

    def test_the_labs_abplus_gate_is_missing_its_level_conditions(self):
        """The lab's gates.py runs the level block for "a" and "ab" only."""
        level = {"box_memory_low", "box_disk_low", "seat_output_stale"}
        abplus = self.theirs["gates"]["abplus"]["events"]
        self.assertFalse([e for e in abplus if e["cond"] in level],
                         "the lab's abplus has no level condition")
        # the replay computes the gate the label names: ab plus telemetry-dark
        self.assertEqual(len(self.mine["abplus"]),
                         len(self.theirs["gates"]["ab"]["events"]) + 6)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    unittest.main(verbosity=2)
