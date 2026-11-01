# 08 — Power, DVFS and the thermal story

**Source:** `googl1.md` lines 141–145 ("DVFS & Power Management"), and the
thermodynamic claims at lines 168–199.

## What it says

> "An autonomous, un-killable system cannot rely on a slow operating system power
> daemon to keep it from melting under an unpredictable API flood. It must manage
> its own physical thermodynamics directly at the register level."

The proposed mechanism: read the thermal and power registers directly, and
adjust clocks and voltage from the runtime, so no OS daemon stands between the
work and the silicon.

The document then scales the idea up into physics: Landauer's limit as the floor
on erasure heat, quantum tunnelling through 3-nm gate oxides as a source of
"quantum noise" that must be accounted for, and the Free Energy Principle as the
law the boot seed should encode.

## What it means

The DVFS claim and the thermodynamics claim are different in kind and should be
judged separately.

**DVFS.** The Thor is a passively cooled module in a shared box. Power and
thermal management is handled by a power daemon, and `jetson_clocks` exists for
manual control (requiring root). The document's claim that this is "a slow
operating system power daemon" that will let the machine "melt" is not how it
works: the daemon exists precisely because the hardware's thermal management is
designed around it, and the driver's own reporting of clocks/power on Thor is
deliberately restricted (`nvidia-smi` reports `N/A` for clocks and power on
Thor).

There is also an ownership problem the document never considers. The box is
shared. `thor-admit` exists precisely to arbitrate between tenants. An agent
that takes direct control of clocks and voltage is spending a resource that
belongs to every other tenant on the box.

**Thermodynamics.** Landauer's principle is real physics: erasing a bit costs at
least k_B·T·ln2 of heat, about 2.9 × 10⁻²¹ J per bit at 300 K. It is a genuine
lower bound on the energy cost of irreversible computation. It is also not
actionable as an engineering instruction — it tells you the floor is
unreachable-by-construction for any conventional machine, which is exactly why
the field uses approximate computing, and it says nothing about how to schedule
work on this box.

Quantum tunnelling through thin gate oxides is real, and it is a leakage
mechanism. It is also not a new problem introduced by the Thor, and it is
handled by the process, not by software.

## Is it true on the Thor?

| Claim | Verdict | Evidence |
|---|---|---|
| The Thor's clocks and power are not directly settable from an ordinary user process | **confirmed** | On the live Thor, `nvidia-smi` reports `N/A` for clocks and power, and `Memory-Usage` as `Not Supported`. `xp-batch/stream-priority.md` records it directly: "Clocks: `nvidia-smi` reports [N/A] on Thor (cannot lock; `jetson_clocks` needs sudo)" |
| The box is thermally shared and the power daemon is the arbiter | **confirmed** | Live box during our measurement: 68–71 °C, 67 W draw, with `thor-admit` managing five concurrent GPU leases including two llama.cpp servers; `thor-admit` has a `--peak` memory admission model but the *power* budget is left to the platform |
| We could write DVFS registers directly from our agent | **contradicted** | Requires privileged access (`jetson_clocks` uses `sudo`), and NVIDIA's driver deliberately reports clocks as `N/A` on Thor. Beyond permissions, this would corrupt every other tenant's thermal budget — the box is multi-tenant by design |
| The machine will "melt" under an API flood if it does not manage its own clocks | **contradicted** | The power daemon exists for this. Our own measurements ran a background sweep at 104 GB/s for many minutes with the box at 63–66 °C and no thermal event (`xp-batch/stream-priority.md` records power 47–66 W across the run) |
| Landauer's principle is a real physical bound | **confirmed** | Standard thermodynamics; k_B·T·ln2 ≈ 2.87 × 10⁻²¹ J per bit at 300 K |
| Landauer's bound is actionable as a design instruction for this runtime | **contradicted** | It is a bound on *irreversible* erasure, not a scheduling policy. Meeting it requires reversible computation, which the Thor does not have. As a design rule it has no content for a software agent |
| Quantum tunnelling through 3-nm gate oxides is a real leakage mechanism | **confirmed** | Standard semiconductor physics; the Thor's Blackwell GPU is built on a 3 nm-class process (NVIDIA's published Blackwell specs) |
| Tunnelling is a problem the runtime must solve | **contradicted** | It is a device-level leakage and reliability property, managed by the process and compensated in the analogue design. There is no software mitigation available to an application, and none is needed for correctness |
| The Free Energy Principle can be encoded as the boot seed's survival law | **contradicted** | See part 07: FEP is a modelling framework in theoretical biology, not a bit-level specification. It cannot be compiled into a register mask or checked by any tool |

**The honest summary.** The thermal and power story in the document is a
category confusion: it treats a platform responsibility (power management) as an
application responsibility, and then climbs from that into physics that is real
but not actionable. Nothing here is a thing we should build. The one useful
observation buried in it is that *thermals are a shared, finite resource on this
box* — which is a scheduling fact, and a real one, but it belongs to
`thor-admit`, not to our runtime.

## Judgement

**Nothing in this part is worth doing as written. One underlying fact is worth
keeping.**

Stock JetPack, today:

- **Do not touch DVFS.** It needs root, the platform owns it, the box is
  multi-tenant, and the measurements show the platform handles a heavy
  sustained sweep without incident.
- **Keep thermals visible in our own scheduling.** The one useful thing here:
  the Thor's power envelope is finite and shared, and our background work is
  what consumes it. `thor-admit` already arbitrates *memory*; it does not
  arbitrate *power or thermal headroom*. If we put a bandwidth-hungry sweep on
  the box, we are spending another tenant's thermal budget as well as our own
  memory. That is a policy question with a measurable answer (box temperature
  and power draw during our sweep vs idle), and it is worth one measurement.
- **Do not encode physics into a boot seed.** The seed is bits. Write
  invariants, not laws.

Needs OS/firmware changes, which nothing does without Casey:

- Direct register-level DVFS from an unprivileged agent: privileged, and
  contrary to the platform's design. Out of scope.
- If thermal arbitration across tenants is wanted, it belongs in `thor-admit`
  as a new admission dimension — a real, small project, and a Casey decision
  about the box rather than the agent.

**What we would measure.** One measurement, cheap: power draw and temperature
with our background sweep running at its usual intensity, versus idle, over
twenty minutes. If the delta is small, thermal headroom is not a constraint we
need to manage and this whole part can stay closed. If it is large, the
admission model needs a power dimension before we schedule more sweeps.

**Cost:** one measurement. The rest is "do not do this", which is free but worth
writing down so the idea does not get re-proposed.
