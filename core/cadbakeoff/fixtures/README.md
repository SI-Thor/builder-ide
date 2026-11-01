# The bakeoff's fixtures

These are the artefacts the model wrote for the cad-bakeoff experiment, and
the prompts it was given. They are here so the numbers in
`docs/lab/exp-cad-bakeoff.md` can be checked without the box and without
the model.

## What is here

For each of the ten props and each of the two kernels:

| file | what it is |
|---|---|
| `<prop>.solidcraft.json` | the model's SolidCraft command script |
| `<prop>.build123d.py` | the model's build123d module |
| `<prop>.<kernel>.prompt.txt` | the exact prompt that produced the artefact |

`replies.json` is the record of every model call: the prompt's SHA-256, the
status, the token counts, and **how many attempts it took** to get a whole
answer.

## The one thing to know about the prompts

The two prompts for a prop differ only in the format block and the one-shot
example. The prop's brief, the rules, the parameters, the bodies, the joint
and the action are byte-identical between the two, which is what makes the
two arms comparable (Hy4 guard 1).

## The one thing to know about the artefacts

They are the model's own work. Nothing in them was hand-edited, and the
harness does not repair them in place: a repair round writes a *new* file
(`repaired.json` / `repaired.py`) and logs the difference against the frozen
spec. The artefacts here are all first-try artefacts.

The `drawer_unit.build123d.py` file is the one that took the most attempts:
the cloud model shares a credential with other seats on this box, and a turn
that lands on top of somebody else's ends without a reply. The retry budget
and the backoff are in `core/cadbakeoff/generate.py`, and the attempt count
for every artefact is in `replies.json` rather than hidden.
