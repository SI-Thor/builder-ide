import sys, numpy as np, torch as th
from pathlib import Path
CRAFTER = Path("/home/caseydigennaro/lm-wt/crafter-lab")
sys.path.insert(0, str(CRAFTER))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lab import core, student as stu
from exp_watching_teachers import load_teacher, skill_splits, skill_order, DEMO_LEAD

frames = load_teacher(CRAFTER / "data/teacher_frames.npz")
names = list(core.ACHIEVEMENTS)
order_all = skill_order(frames, names)
counts = {n: int((frames["events"] == names.index(n)).sum()) for n in order_all}
chosen = sorted(order_all, key=lambda n: -counts[n])[:6]
order = [n for n in order_all if n in chosen]
splits = skill_splits(frames, names, order, 20261101)

obs_space, action_space = core.make_spaces()
pol = stu.build_policy(obs_space, action_space, seed=0)
stud = stu.Student(pol, "cpu")

def report(label, student):
    out = []
    for name in order:
        m = splits[name]["eval"]
        preds = student.predict_batch(frames["obs"][m])
        out.append((name, float((preds == frames["actions"][m]).mean())))
    # the marginal (constant-action) baseline per skill
    base = []
    for name in order:
        m = splits[name]["eval"]
        a = frames["actions"][m]
        vals, counts_ = np.unique(a, return_counts=True)
        base.append((name, float(counts_.max() / len(a))))
    print(label)
    for (n, v), (n2, b) in zip(out, base):
        print(f"   {n:22s} agreement={v:.3f}  constant-baseline={b:.3f}")
    # overall on the trajectory subsample
    traj = np.random.RandomState(20261101).choice(len(frames["actions"]), 5000, replace=False)
    preds = student.predict_batch(frames["obs"][traj])
    print(f"   overall(trajectory) = {float((preds==frames['actions'][traj]).mean()):.3f}")

report("UNTRAINED policy", stud)

pol2 = stu.build_policy(obs_space, action_space, seed=0)
stud2 = stu.Student(pol2, "cpu")
stud2.load(CRAFTER / "results/B/policy_final.pt")
report("crafter-lab student B (final)", stud2)
