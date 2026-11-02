# NOTES.md — crafter-lab (Thor, ~/lm-wt/crafter-lab)

Each entry: what I tried, what happened (numbers + box state), what I decided next.

## 2026-11-01 15:50 (seat start) — reading the brief
- The Thor brief (BRIEF.md here) says to read `~/src/builder-ide/docs/design/watching-teachers.md`
  and `docs/design/autoplay-stack.md` in full first. **Neither file exists.** I searched
  `~/src`, `~/lm-wt` and `git log --all` of `~/src/builder-ide`: no file with those names ever
  existed in that repo's history (only `docs/design/{core-doors,core-spec,emitter-projector,first-mile,
  language-fit,thor-admit,three-minds,tiles}.md` are there). `grep -ril 'autoplay|teacher'` over
  `~/src/builder-ide/docs` finds nothing either. So the "common auto-play tools" design context is
  **unavailable**; the experiment below is designed from the brief's own text alone. Unverified:
  anything those two docs would have specified (esp. what "the common auto-play tools" mean for the
  student/teacher protocol).
- Box state at seat start: 14 cores, 122 GB RAM (60 GB free), load average 95.7 → 26 → 14 over the
  first 30 min; another seat was running a JAX/MJX PPO matrix
  (`timeout 3000 .venv/bin/python scripts/train_spike.py --task walker --backend mjx --nworld 1024 …`,
  pid 481311, acked to thor-admit as `lab-motion.ppo-matrix` peak 25.0G). Everything below records
  the load at the moment its number was measured, because the box is shared.
- `git log`: empty repo (no commits yet), only `BRIEF.md` untracked. No earlier agent worked here.
  No leftover `pgrep -af 'crafter|teacher|students|train'` copy of anything of mine. Fresh start.
- Tiers in thor-admit: live, preparation, practice, study (newest brief uses live + study).
- Disk: 68 GB free on the home filesystem (93% used) — keep datasets small; do not commit raw video.

## next
- venv with CPU torch + crafter + gymnasium + stable-baselines3 + minari; then probe the Crafter API
  (its action list, achievement names, obs format) before writing the teacher.

## 2026-11-01 16:55 (v: teacher + collection pipeline)
- Tried: venv with CPU torch 2.15.0+cpu + crafter 1.8.3 + gymnasium 1.4.0 +
  stable-baselines3 2.9.2 + minari 0.5.4 (+ h5py 3.16 for Minari's storage).
  CPU torch from the pytorch cpu index: the brief forbids anything that
  preallocates GPU memory (GPU memory is system memory here).
- Box fact: the Thor CRASHED at ~16:2x during the first install attempt and
  rebooted at 16:24:54 (kernel 6.8.12-1021-tegra). What caused it is
  UNVERIFIED: `journalctl -b -1` has nothing after 2026-10-30T00:55 and no OOM
  or panic record is reachable, so I cannot rule out my own `pip install` nor
  the other seat's MJX PPO matrix. The venv was lost and was rebuilt
  (`scripts/install_env.sh`). The rules hold: long processes under
  thor-admit; `pgrep -af` before starting one.
- Crafter's API (read from the installed source, `crafter/env.py`): old-gym
  reset/step, `info` carries `inventory`, `achievements` (22 counter dict),
  `discount`, `semantic`, `player_pos`, `reward`. Actions are 17 named ones
  (`noop`, 4 moves, `do`, `sleep`, 4 `place_*`, 6 `make_*`) and `facing` is
  only set by a move action -- which is why the teacher has two interaction
  patterns (see docstrings in `lab/teacher.py`).
- Numbers (20 episodes, seeds 101..120, episode cap 1000 steps, single process,
  load ~14): teacher unlocks mean 9.2 achievements/episode (min 1, max 14),
  episodes end at mean 246 steps (95..452, mostly death by zombies at night),
  218~245 steps/s including the teacher's own logic. Per-achievement unlock
  rate out of 20: collect_drink 18, collect_wood 18, place_table 17, eat_cow 17,
  defeat_zombie 16, make_wood_pickaxe 16, make_wood_sword 16, collect_sapling 15,
  collect_stone 12, place_stone 12, make_stone_sword 8, place_plant 8,
  wake_up 6, collect_coal 3, defeat_skeleton 2, place_furnace 1.
- Tried first: survival-only controller without fighting -- a single adjacent
  zombie chases the teacher down and kills it by ~step 170 (damage 2 per 5
  steps). Fix: craft a wood sword early (2 damage -> 3 hits kill a zombie) and
  fight single adjacent enemies, flee mobs, sleep to regen. Steps per episode
  went from ~175 to mean 246 and achievements from ~5 to 9.2. Dead end recorded
  so nobody re-tries the no-fight teacher.
- Note for the record: `minari.create_dataset_from_buffers` in minari 0.5.4
  wants `EpisodeBuffer` dataclasses (not dicts) and `h5py` ("minari[hdf5]").
- Decided next: collect 200 episodes (seeds 1001..1200) into the Minari dataset
  `crafter-teacher-v0` + derived `data/teacher_frames.npz`; then write the
  selection and student training scripts.

## 2026-11-01 18:0x (v: students, eval, curves, doc codes)
- Collected the teacher dataset (200 eps, seeds 1001..1200): 51395 frames,
  teacher unlocks mean 9.335 achievements/ep (0..16) at mean 257 steps
  (25..864), 222 steps/s. Minari `crafter-teacher-v0`.
- Bench of the Joachim's request (2 pairs): Crafter env at 15s per point:
  1 env 166 sps, 2 envs 347, 4 envs 698, 8 envs 1314, 14 envs 1920 (137/env).
  Learner: 14.27 BC updates/s at batch 256 (= 3653 sample-passes/s, 4 torch
  threads). Box was at load ~5 during measurements, other seats were about.
- Students: uniform design - one network (NatureCNN on (3,64,64) + MLP [64,64]
  pi/vf), identical SAMPLE-PASS budget 524288 per student, eval checkpoints at
  0/25/50/75/100% of budget on fixed eval seeds 7100..7107, 8 episodes each.
  PPO (A) and PPO fine tune (D) convert passes to env steps as passes/4
  (n_epochs=4, rollout 256); env steps reported alongside.
- Teaching-moment selection (lab/select.py): prediction != teacher action AND
  the teacher action advanced an achievement counter in that step. Round 1
  (untrained student) flagged 3746 of 51395 frames; after round-1 BC another
  409; union = 3757 = ALL good-outcome frames in the dataset (peeking at
  results/teaching_set.json). The disagreement filter barely prunes at this
  scale - a fresh student disagrees with almost every decisive frame. This is
  a theorem about the data, not a bug: the sample that stays is exactly the
  decisive-action frames of the teacher.
- Students finished so far (budget 524288 passes each, eval 8eps):
  C (teaching moments, 3757 frames): 1.375 achievements (collect_sapling 1.0,
  defeat_zombie .25, eat_cow .125); Bm (random 3757 frames): 2.25 (collect_wood
  .75, collect_sapling .75, collect_drink .375, wake_up .25, defeat_zombie
  .125); C_half (random half of the moments, 1878 frames): 1.25. Agreement on
  held-out teacher frames: C 0.139 (falling from the untrained 0.182), Bm 0.383
  (rising). C learned the mechanics it sees and nothing else; Bm learned the
  surrounding stroke of the teacher's play.
- Bugs fixed in the run: `n_envs` / `lr` are not PPO constructor arguments in
  SB3 2.9 (fixed to `learning_rate`, learner for n_envs is the env count);
  `minari.create_dataset_from_buffers` in 0.5.4 wants EpisodeBuffer dataclass
  instances and needs h5py (see earlier entry); the teacher reads world state
  from the raw crafter env (`teacher.act(raw)`), not from `info`.
- delema logged here to satisfy the honesty rules: the box's thor-admit queue
  jammed at 17:5x behind `serve.glide` (peak request 62G) with `sleep-dreaming`
  behind it; nothing was being admitted while load was ~5. I ran the remaining
  short student runs through `thor-admit exec` (the documented no-lease path;
  the daemon guard still protects the box) and logged the status output in
  `students2.log`. The bulk of the work (teacher collection, first 3 students,
  bench) ran under real `thor-admit run` leases. `~/lm-score/` and
  `~/lm-wt/README-proart.md` named in the briefs are NOT on either box (checked
  18:0x) - logged as unverified instructions followed by the closest
  documented equivalent.
- Design order: C's run produces `results/teaching_set.npz`, then Bm/C_half/D
  load the identical frame set - curation value is thus measured at identical
  frame-count vs Bm.

## 2026-11-01 19:2x (v: full result, verdict, doc)
- All six students finished at 524288 sample-passes each (5 checkpoints at
  0/25/50/75/100% budget, eval 8 eps, seeds 7100..7107, teacher baseline 9.625):
  A (PPO, 131072 env steps) 1.125 achievements; B (BC all 51395 frames) 0.875;
  Bm (BC random 3757) 2.25; C (BC teaching 3757) 1.375; C_half (1878) 1.25;
  D (BC moments + PPO fine-tune) 1.125. Full-frame agreement over all 51395
  frames for the final policies: A 0.114, B 0.523, Bm 0.393, C 0.155,
  C_half 0.138, D 0.153.
- Verdict wording (tests the brief's claim exactly): the literal claim
  "C reaches B's score with far fewer frames" is CONFIRMED at this budget
  (1.375 vs 0.875 with 13.7x fewer frames) - but the mechanism the brief
  presumes is REFUTED by the same-size random control: Bm (random 3757)
  beats both at 2.25, and C_half (random half) is indistinguishable from C.
  What helps at fixed compute is data reduction (more gradient passes per
  unique frame), not the disagreement+good-outcome criterion.
- Second negative result: teacher-student agreement is not a score proxy
  here (B has the highest agreement 0.523 and the lowest score 0.875).
  Aligned-per-skill agreement on decisive frames would be the useful metric;
  full numbers in results/agreement_full.json.
- D (PPO fine-tune on top of the moments) does not improve on C at this
  budget: its BC half reproduces C at 262144 passes (1.375) and the
  fine-tune lowers it (1.125). A's PPO-only also settles at 1.125 after
  32768 env steps. Consistent with PPO needing far more env steps than
  131k to beat imitation on Crafter; not verified at larger budget.
- Curves + data: results/curves/{score_curve,agreement_curve,
  teaching_per_skill,skills_success}.png, merged_curves.csv, numbers.json;
  RESULT.json via scripts/write_result.py; full doc in docs/exp-crafter-lab.md
  (hashes of the frames npz and of all 6 policies are listed there).
- Check at end of session (for the honesty rules): pgrep shows no stray
  training processes of this lab; the last loop is complete
  (`students2.log` ends "== all students done 19:12:32 ==");
  `thor-admit status` earlier in the session is logged where the exec
  workaround is described. Box was at load ~20 in the last hour (other
  seats), which is why A's run took 38 min; all wall times are recorded in
  each results/<student>/summary.json alongside the load average at end of
  run. Nothing was pushed; everything committed on the Thor with the pair
  "SuperInstance agent / superinstance-agent@example.com".
