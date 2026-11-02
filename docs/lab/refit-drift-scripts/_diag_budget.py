import sys, numpy as np, torch as th, time
from pathlib import Path
CRAFTER = Path("/home/caseydigennaro/lm-wt/crafter-lab")
sys.path.insert(0, str(CRAFTER))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab import core, student as stu
from exp_watching_teachers import load_teacher, skill_splits, skill_order

frames = load_teacher(CRAFTER / "data/teacher_frames.npz")
names = list(core.ACHIEVEMENTS)
order_all = skill_order(frames, names)
counts = {n: int((frames["events"] == names.index(n)).sum()) for n in order_all}
chosen = sorted(order_all, key=lambda n: -counts[n])[:6]
order = [n for n in order_all if n in chosen]
splits = skill_splits(frames, names, order, 20261101)
traj = np.random.RandomState(20261101).choice(len(frames["actions"]), 5000, replace=False)

obs_space, action_space = core.make_spaces()
skill = "collect_wood"
m = splits[skill]["eval"]
a = frames["actions"][m]
vals, cnt = np.unique(a, return_counts=True)
print(f"{skill}: constant-baseline={cnt.max()/len(a):.3f}  n_train={len(splits[skill]['train'])}")

for P in (16384, 65536, 262144):
    pol = stu.build_policy(obs_space, action_space, seed=0)
    stud = stu.Student(pol, "cpu")
    rng = np.random.RandomState(0)
    t0 = time.monotonic()
    stu.bc_train(stud, frames["obs"][splits[skill]["train"]],
                 frames["actions"][splits[skill]["train"]], P, rng=rng)
    dt = time.monotonic() - t0
    preds = stud.predict_batch(frames["obs"][m])
    agree = float((preds == a).mean())
    tp = stud.predict_batch(frames["obs"][traj])
    overall = float((tp == frames["actions"][traj]).mean())
    # how state-dependent is it? the share of distinct predicted actions
    uniq = len(np.unique(preds)) / 17.0
    print(f"  passes={P:7d} ({dt:5.0f}s)  skill_agreement={agree:.3f}  overall={overall:.3f} "
          f"distinct_actions_used={uniq:.2f}")
