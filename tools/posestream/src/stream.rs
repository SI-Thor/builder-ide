//! The emitter and the projectors.
//!
//! The emitter owns the canon (the world) and the spatial index. For every subscriber it
//! keeps what that subscriber has already been told, and at each delivery it sends only the
//! difference: objects that entered the region (absolute pose), objects that left (id only),
//! and objects whose pose moved (quantised delta). The projector is the mirror image: it
//! holds the same per-object state, applies the deltas, and can therefore reproduce the
//! emitter's ground truth exactly at every tick it is delivered.

use crate::space::*;
use crate::wire::*;
use crate::world::*;

/// How a pose delta is measured.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Mode {
    /// The delta is measured from the last position this subscriber was told.
    Direct,
    /// The delta is measured from the position the projector would *predict* from the motion
    /// channel it already holds (constant-velocity extrapolation), so a smooth object costs
    /// nothing at all. The projector applies exactly the same prediction, so the two agree.
    Predictive,
}

/// What a subscriber has been told about one object. It lives next to the object's id in the
/// subscriber's set, so the emitter's per-delivery work is sequential in memory.
#[derive(Clone, Copy, Default)]
pub struct ObjState {
    /// The last quantised position sent (the truth at `anchor_us`).
    pub pos: [i32; 3],
    /// The last quantised velocity sent, in 1/64 quantum per tick.
    pub vel: [i32; 3],
    /// The velocity in effect when the position was last corrected: the prediction is a
    /// snapshot, `pos + anchor_vel * (t - anchor)`.
    pub anchor_vel: [i32; 3],
    /// The time the held position refers to, in microticks (1e6 microticks = 1 tick).
    ///
    /// The emitter always anchors at a whole tick. A receiver that back-dates anchors at
    /// the packet's tick, so its held position is exactly the emitter's truth at that tick;
    /// a receiver that does not back-dates anchors at the packet's arrival, and its held
    /// position is then the truth plus the motion it double-counted.
    pub anchor_us: u64,
}

pub struct SubState {
    /// Objects in the subscriber's region at the last delivery (ascending ids).
    pub set: Vec<u32>,
    /// The state of each object, parallel to `set`.
    pub objs: Vec<ObjState>,
    /// The tick of the last packet the emitter sent to this subscriber.
    pub version: u32,
    pub started: bool,
}

impl SubState {
    fn new() -> SubState {
        SubState {
            set: Vec::new(),
            objs: Vec::new(),
            version: 0,
            started: false,
        }
    }
}

pub struct Emitter {
    pub mode: Mode,
    /// The exit hysteresis on the interest regions, in metres (0: off). An object that has
    /// drifted just outside the region stays in the subscriber's set until it is this far
    /// outside, instead of being evicted and re-entered on the next delivery.
    pub hysteresis: f64,
    /// Send the leave list as absolute 16-bit ids (the "2-byte evict") instead of
    /// delta-coded varints.
    pub evict_abs: bool,
    /// phase timers (diagnostics)
    pub t_region: f64,
    pub t_records: f64,
    pub t_encode: f64,
    pub world: World,
    pub grid: Grid,
    pub subs: Vec<Subscriber>,
    pub state: Vec<SubState>,
    // scratch buffers (the emitter is single threaded, so one set is enough)
    cand: Vec<u32>,
    new_set: Vec<u32>,
    new_objs: Vec<ObjState>,
    /// The previous set, copied out so the hysteresis can read it while the scratch
    /// buffers are written.
    prev_copy: Vec<u32>,
    /// The members the hysteresis keeps: they failed the enter test but passed the exit one.
    retain: Vec<u32>,
    /// The merge of `new_set` and `retain`.
    merged: Vec<u32>,
    mark: Vec<u64>,
    pub packet: Packet,
    pub out: Vec<u8>,
    scratch: EncodeScratch,
}

impl Emitter {
    pub fn new(seed: u64) -> Emitter {
        let world = World::new(seed);
        let mut grid = Grid::new(WORLD_MIN, WORLD_MAX, 10.0, N_OBJECTS);
        for (i, p) in world.pos.iter().enumerate() {
            grid.insert(i as u32, *p);
        }
        let subs = build_subscribers(seed);
        let state = (0..subs.len()).map(|_| SubState::new()).collect();
        Emitter {
            mode: Mode::Direct,
            hysteresis: 0.0,
            evict_abs: false,
            t_region: 0.0,
            t_records: 0.0,
            t_encode: 0.0,
            world,
            grid,
            subs,
            state,
            cand: Vec::with_capacity(4096),
            new_set: Vec::with_capacity(4096),
            new_objs: Vec::with_capacity(4096),
            prev_copy: Vec::with_capacity(4096),
            retain: Vec::with_capacity(4096),
            merged: Vec::with_capacity(4096),
            mark: vec![0u64; (N_OBJECTS + 63) / 64],
            packet: Packet::default(),
            out: Vec::with_capacity(1 << 16),
            scratch: EncodeScratch::default(),
        }
    }

    /// Advance the canon and keep the spatial index in step.
    pub fn step_world(&mut self) {
        self.world.step();
        for (i, p) in self.world.pos.iter().enumerate() {
            self.grid.update(i as u32, *p);
        }
    }

    #[inline]
    fn mark_set(mark: &mut [u64], id: u32) {
        let w = (id / 64) as usize;
        mark[w] |= 1u64 << (id % 64);
    }

    #[inline]
    fn mark_clear(mark: &mut [u64], id: u32) {
        let w = (id / 64) as usize;
        mark[w] &= !(1u64 << (id % 64));
    }

    /// The objects currently in the subscriber's region, ascending.
    ///
    /// With hysteresis on, an object that was in the region at the last delivery and is
    /// still within `hysteresis` metres of it stays in the set: the exit test is the enter
    /// test with the region grown by that margin. Without it, the membership is the enter
    /// test alone and an object on the boundary churns in and out.
    fn region_set(&mut self, si: usize, tick: u32) {
        let region = self.subs[si].region_at(tick);
        let (lo, hi) = region.aabb();
        let hyst = self.hysteresis;
        self.cand.clear();
        // the candidate box is grown by the hysteresis margin, so a member that has drifted
        // just outside is still a candidate
        let (elo, ehi) = if hyst > 0.0 {
            (
                [lo[0] - hyst, lo[1] - hyst, lo[2] - hyst],
                [hi[0] + hyst, hi[1] + hyst, hi[2] + hyst],
            )
        } else {
            (lo, hi)
        };
        self.grid.query_aabb(elo, ehi, &mut self.cand);
        for id in self.cand.iter() {
            let id = *id;
            let p = self.world.pos[id as usize];
            if region.contains(p) {
                Self::mark_set(&mut self.mark, id);
            }
        }
        self.new_set.clear();
        for (w, word) in self.mark.iter().enumerate() {
            let mut bits = *word;
            while bits != 0 {
                let b = bits.trailing_zeros() as usize;
                self.new_set.push((w * 64 + b) as u32);
                bits &= bits - 1;
            }
        }
        for id in self.new_set.iter() {
            Self::mark_clear(&mut self.mark, *id);
        }
        if hyst <= 0.0 {
            return;
        }
        // The members of the previous set that failed the enter test but pass the exit test
        // stay. The previous set is copied out first: the scratch buffers are written while
        // it is read.
        self.prev_copy.clear();
        self.prev_copy.extend_from_slice(&self.state[si].set);
        self.retain.clear();
        for &id in self.prev_copy.iter() {
            if self.new_set.binary_search(&id).is_ok() {
                continue; // already inside the region
            }
            let p = self.world.pos[id as usize];
            if region.contains_exit(p, hyst) {
                self.retain.push(id);
            }
        }
        // merge the two ascending lists
        self.merged.clear();
        let (mut i, mut j) = (0usize, 0usize);
        while i < self.new_set.len() && j < self.retain.len() {
            if self.new_set[i] <= self.retain[j] {
                self.merged.push(self.new_set[i]);
                i += 1;
            } else {
                self.merged.push(self.retain[j]);
                j += 1;
            }
        }
        self.merged.extend_from_slice(&self.new_set[i..]);
        self.merged.extend_from_slice(&self.retain[j..]);
        std::mem::swap(&mut self.new_set, &mut self.merged);
    }

    /// Build the packet for `si` at `tick`. A subscriber with no state (a late joiner) or a
    /// subscriber that asks for a resync gets a keyframe: the full region, absolute poses.
    pub fn build_packet(&mut self, si: usize, tick: u32, keyframe: bool) {
        let t0 = std::time::Instant::now();
        self.region_set(si, tick);
        let t1 = std::time::Instant::now();
        self.t_region += (t1 - t0).as_secs_f64() * 1000.0;
        let mode = self.mode;
        let evict_abs = self.evict_abs;
        let Emitter {
            world,
            state,
            packet,
            new_set,
            new_objs,
            ..
        } = self;
        let st = &mut state[si];
        let keyframe = keyframe || !st.started;

        packet.flags = FLAG_VELOCITY;
        if evict_abs {
            packet.flags |= FLAG_EVICT_ABS;
        }
        packet.tick = tick;
        packet.n_region = new_set.len() as u32;
        packet.enter.clear();
        packet.leave.clear();
        packet.change.clear();
        packet.bitmap.clear();
        new_objs.clear();

        if keyframe {
            packet.flags |= FLAG_KEYFRAME;
            packet.n_prev = 0;
            packet.since_version = tick;
            for id in new_set.iter() {
                let id = *id;
                let q = quantise(world.pos[id as usize]);
                let v = quantise_vel(world.vel[id as usize]);
                packet.enter.push(EnterRec {
                    id,
                    pos: [q[0] as u16, q[1] as u16, q[2] as u16],
                    vel: [v[0] as i16, v[1] as i16, v[2] as i16],
                });
                new_objs.push(ObjState {
                    pos: q,
                    vel: v,
                    anchor_vel: v,
                    anchor_us: tick as u64 * TICK_US,
                });
            }
        } else {
            packet.n_prev = st.set.len() as u32;
            packet.since_version = st.version;
            let nprev = st.set.len();
            packet.bitmap.resize((nprev + 7) / 8, 0);
            let mut i = 0usize; // into the previous set
            let mut j = 0usize; // into the current region set
            while j < new_set.len() {
                let nid = new_set[j];
                if i < nprev && st.set[i] < nid {
                    packet.leave.push(st.set[i]);
                    i += 1;
                } else if i < nprev && st.set[i] == nid {
                    // in the region both times: has its pose moved since we last spoke?
                    let mut s = st.objs[i];
                    let q = quantise(world.pos[nid as usize]);
                    let v = quantise_vel(world.vel[nid as usize]);
                    let dpos = match mode {
                        Mode::Direct => [q[0] - s.pos[0], q[1] - s.pos[1], q[2] - s.pos[2]],
                        Mode::Predictive => {
                            // what the projector will have predicted for itself: the anchor
                            // snapshot, extrapolated over the time since it was corrected
                            let dt_us = tick as i64 * TICK_US as i64 - s.anchor_us as i64;
                            let d = vel_displacement_us(s.anchor_vel, dt_us);
                            [
                                q[0] - (s.pos[0] + d[0]),
                                q[1] - (s.pos[1] + d[1]),
                                q[2] - (s.pos[2] + d[2]),
                            ]
                        }
                    };
                    let dvel = [v[0] - s.vel[0], v[1] - s.vel[1], v[2] - s.vel[2]];
                    let has_pos = dpos != [0, 0, 0];
                    let has_vel = dvel != [0, 0, 0];
                    if has_pos || has_vel {
                        packet.change.push(ChangeRec { id: nid, dpos, dvel, has_pos, has_vel });
                        if has_pos {
                            s.pos = q;
                            s.anchor_us = tick as u64 * TICK_US;
                            s.anchor_vel = v;
                        }
                        if has_vel {
                            s.vel = v;
                        }
                        packet.bitmap[i / 8] |= 1 << (i % 8);
                    }
                    new_objs.push(s);
                    i += 1;
                    j += 1;
                } else {
                    // entered the region
                    let q = quantise(world.pos[nid as usize]);
                    let v = quantise_vel(world.vel[nid as usize]);
                    packet.enter.push(EnterRec {
                        id: nid,
                        pos: [q[0] as u16, q[1] as u16, q[2] as u16],
                        vel: [v[0] as i16, v[1] as i16, v[2] as i16],
                    });
                    new_objs.push(ObjState {
                        pos: q,
                        vel: v,
                        anchor_vel: v,
                        anchor_us: tick as u64 * TICK_US,
                    });
                    j += 1;
                }
            }
            while i < nprev {
                packet.leave.push(st.set[i]);
                i += 1;
            }
            // Bitmap or id list? The bitmap costs ceil(nprev/8) bytes; the id list costs about
            // one byte per changed object. Use whichever is smaller.
            let bitmap_cost = (nprev + 7) / 8;
            if packet.change.len() > bitmap_cost {
                packet.flags |= FLAG_CHANGE_BITMAP;
            } else {
                packet.bitmap.clear();
            }
        }

        // The subscriber's set is now the region set.
        st.set.clear();
        st.set.extend_from_slice(new_set);
        st.objs.clear();
        st.objs.extend_from_slice(new_objs);
        st.version = tick;
        st.started = true;

        let t2 = std::time::Instant::now();
        self.t_records += (t2 - t1).as_secs_f64() * 1000.0;
        self.out.clear();
        crate::wire::encode(&mut self.packet, &mut self.out, &mut self.scratch);
        self.t_encode += t2.elapsed().as_secs_f64() * 1000.0;
    }

    /// True when this subscriber is due a delivery at `tick`.
    pub fn due(&mut self, si: usize, tick: u32) -> bool {
        let s = &mut self.subs[si];
        if tick < s.join_tick {
            return false;
        }
        if tick >= s.next_due {
            s.next_due = tick + s.interval;
            true
        } else {
            false
        }
    }
}

// ------------------------------------------------------------------ projector

#[derive(Debug)]
pub enum ApplyError {
    /// The packet's base version is not the state this projector holds.
    Gap { held: u32, offered: u32 },
}

pub struct Projector {
    pub mode: Mode,
    /// True: the receiver back-dates the correction, anchoring its state at the packet's
    /// tick. False: it anchors at the packet's arrival, which is what a receiver does when
    /// it applies a correction "now" without asking when the correction was computed.
    pub backdate: bool,
    /// Objects in the subscriber's region (ascending ids).
    pub set: Vec<u32>,
    /// The state of each object, parallel to `set`.
    pub objs: Vec<ObjState>,
    /// The tick of the last packet applied.
    pub version: u32,
    pub started: bool,
    scratch_set: Vec<u32>,
    scratch_objs: Vec<ObjState>,
}

impl Projector {
    pub fn new() -> Projector {
        Projector {
            mode: Mode::Direct,
            backdate: true,
            set: Vec::new(),
            objs: Vec::new(),
            version: 0,
            started: false,
            scratch_set: Vec::new(),
            scratch_objs: Vec::new(),
        }
    }

    /// The state this projector holds for an object.
    pub fn state_of(&self, id: u32) -> Option<ObjState> {
        self.set
            .binary_search(&id)
            .ok()
            .and_then(|i| self.objs.get(i).copied())
    }

    /// Apply a packet.
    ///
    /// `anchor_us` is the time the packet's corrections belong to, in microticks: the
    /// packet's own tick when the receiver back-dates, the packet's arrival when it does
    /// not. Back-dating is what keeps the delay out of the state: the held position then
    /// is the emitter's truth at the packet's tick, exactly, whatever the link did.
    pub fn apply(&mut self, pkt: &Packet, anchor_us: u64) -> Result<(), ApplyError> {
        if pkt.flags & FLAG_KEYFRAME != 0 {
            self.set.clear();
            self.objs.clear();
            for e in &pkt.enter {
                self.set.push(e.id);
                self.objs.push(ObjState {
                    pos: [e.pos[0] as i32, e.pos[1] as i32, e.pos[2] as i32],
                    vel: [e.vel[0] as i32, e.vel[1] as i32, e.vel[2] as i32],
                    anchor_vel: [e.vel[0] as i32, e.vel[1] as i32, e.vel[2] as i32],
                    anchor_us,
                });
            }
            self.version = pkt.tick;
            self.started = true;
            return Ok(());
        }
        if !self.started || pkt.since_version != self.version {
            return Err(ApplyError::Gap {
                held: self.version,
                offered: pkt.since_version,
            });
        }

        // 1. the position corrections. They must use the anchor velocity the projector held
        //    *before* this packet, exactly as the emitter measured the residual.
        let mut k = 0usize;
        for j in 0..self.set.len() {
            while k < pkt.change.len() && pkt.change[k].id < self.set[j] {
                k += 1;
            }
            if k >= pkt.change.len() {
                break;
            }
            if pkt.change[k].id != self.set[j] {
                continue;
            }
            let c = &pkt.change[k];
            if c.has_pos {
                let s = &mut self.objs[j];
                let base = match self.mode {
                    Mode::Direct => s.pos,
                    Mode::Predictive => {
                        let dt_us = anchor_us as i64 - s.anchor_us as i64;
                        let d = vel_displacement_us(s.anchor_vel, dt_us);
                        [s.pos[0] + d[0], s.pos[1] + d[1], s.pos[2] + d[2]]
                    }
                };
                s.pos = [base[0] + c.dpos[0], base[1] + c.dpos[1], base[2] + c.dpos[2]];
            }
            k += 1;
        }

        // 2. the velocity updates, then re-anchor the corrected objects: the new anchor is
        //    the corrected pose plus the velocity now in effect.
        let mut k = 0usize;
        for j in 0..self.set.len() {
            while k < pkt.change.len() && pkt.change[k].id < self.set[j] {
                k += 1;
            }
            if k >= pkt.change.len() {
                break;
            }
            if pkt.change[k].id != self.set[j] {
                continue;
            }
            let c = &pkt.change[k];
            let s = &mut self.objs[j];
            if c.has_vel {
                s.vel = [s.vel[0] + c.dvel[0], s.vel[1] + c.dvel[1], s.vel[2] + c.dvel[2]];
            }
            if c.has_pos {
                s.anchor_us = anchor_us;
                s.anchor_vel = s.vel;
            }
            k += 1;
        }

        // 3. rebuild the set: (previous - left) + entered, ascending.
        let mut out_set = std::mem::take(&mut self.scratch_set);
        let mut out_objs = std::mem::take(&mut self.scratch_objs);
        out_set.clear();
        out_objs.clear();
        let mut li = 0usize;
        let mut i = 0usize;
        let mut e = 0usize;
        while i < self.set.len() || e < pkt.enter.len() {
            let take_old = if e >= pkt.enter.len() {
                true
            } else if i >= self.set.len() {
                false
            } else {
                self.set[i] < pkt.enter[e].id
            };
            if take_old {
                let id = self.set[i];
                while li < pkt.leave.len() && pkt.leave[li] < id {
                    li += 1;
                }
                if !(li < pkt.leave.len() && pkt.leave[li] == id) {
                    out_set.push(id);
                    out_objs.push(self.objs[i]);
                }
                i += 1;
            } else {
                let en = &pkt.enter[e];
                out_set.push(en.id);
                out_objs.push(ObjState {
                    pos: [en.pos[0] as i32, en.pos[1] as i32, en.pos[2] as i32],
                    vel: [en.vel[0] as i32, en.vel[1] as i32, en.vel[2] as i32],
                    anchor_vel: [en.vel[0] as i32, en.vel[1] as i32, en.vel[2] as i32],
                    anchor_us,
                });
                e += 1;
            }
        }
        std::mem::swap(&mut self.set, &mut out_set);
        std::mem::swap(&mut self.objs, &mut out_objs);
        self.scratch_set = out_set;
        self.scratch_objs = out_objs;
        self.version = pkt.tick;
        Ok(())
    }

    /// The pose the projector holds for an object at `tick`.
    ///
    /// * Direct mode: the position *is* the truth at the last correction (deltas accumulate
    ///   to it), so it is current at every delivery tick.
    /// * Predictive mode: the position is the truth at the object's anchor; the pose at
    ///   `tick` is that anchor extrapolated with the motion channel.
    pub fn pose_at(&self, id: u32, tick: u32) -> [i32; 3] {
        self.pose_at_us(id, tick as u64 * TICK_US)
    }

    /// The pose the projector holds for an object at a time given in microticks.
    pub fn pose_at_us(&self, id: u32, us: u64) -> [i32; 3] {
        let s = match self.state_of(id) {
            Some(s) => s,
            None => return [0; 3],
        };
        match self.mode {
            Mode::Direct => s.pos,
            Mode::Predictive => {
                // the motion channel works both ways: a receiver that did not back-date
                // holds an anchor later than the tick it is asked about
                let dt_us = us as i64 - s.anchor_us as i64;
                let d = vel_displacement_us(s.anchor_vel, dt_us);
                [s.pos[0] + d[0], s.pos[1] + d[1], s.pos[2] + d[2]]
            }
        }
    }

    /// The projector's predicted quantised position of an object at `tick`, using the motion
    /// channel it already holds (constant-velocity extrapolation between deliveries).
    pub fn predicted(&self, id: u32, tick: u32) -> [i32; 3] {
        match self.mode {
            Mode::Direct => {
                let s = match self.state_of(id) {
                    Some(s) => s,
                    None => return [0; 3],
                };
                let dt_us = tick as i64 * TICK_US as i64 - self.version as i64 * TICK_US as i64;
                let d = vel_displacement_us(s.anchor_vel, dt_us);
                [s.pos[0] + d[0], s.pos[1] + d[1], s.pos[2] + d[2]]
            }
            Mode::Predictive => self.pose_at(id, tick),
        }
    }

    /// The object's velocity expressed in the subscriber's own frame, minus the subscriber's own
    /// motion: the apparent motion a projector would use for optical flow.
    pub fn apparent_velocity(&self, id: u32, region: &Region, eye_vel: [f64; 3]) -> [f64; 3] {
        let v = match self.state_of(id) {
            Some(s) => dequantise_vel(s.vel),
            None => return [0.0; 3],
        };
        let rel = [v[0] - eye_vel[0], v[1] - eye_vel[1], v[2] - eye_vel[2]];
        [dot(rel, region.right), dot(rel, region.up), dot(rel, region.fwd)]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// End to end: the emitter's packets must let a projector reproduce the ground truth.
    #[test]
    fn projector_reproduces_the_ground_truth() {
        for mode in [Mode::Direct, Mode::Predictive] {
            let mut em = Emitter::new(2024);
            em.mode = mode;
            let n = em.subs.len();
            let mut proj: Vec<Projector> = (0..n).map(|_| Projector::new()).collect();
            for p in proj.iter_mut() {
                p.mode = mode;
            }
            let mut errors = 0u64;
            let mut checked = 0u64;
            for tick in 1..=240u32 {
                em.step_world();
                for si in 0..n {
                    if !em.due(si, tick) {
                        continue;
                    }
                    em.build_packet(si, tick, false);
                    let pkt = crate::wire::decode(&em.out, &proj[si].set).expect("decode");
                    proj[si]
                        .apply(&pkt, pkt.tick as u64 * TICK_US)
                        .expect("apply");
                    for &id in &em.state[si].set {
                        let truth = quantise(em.world.pos[id as usize]);
                        if proj[si].pose_at(id, tick) != truth {
                            errors += 1;
                        }
                        checked += 1;
                    }
                }
            }
            assert_eq!(errors, 0, "{:?}: reconstruction errors", mode);
            assert!(checked > 10_000, "{:?}: only {} states checked", mode, checked);
        }
    }

    /// A lost packet must be detected and repaired by a keyframe.
    #[test]
    fn a_lost_packet_is_detected_and_resynced() {
        let mut em = Emitter::new(7);
        em.mode = Mode::Predictive;
        let mut proj = Projector::new();
        proj.mode = Mode::Predictive;
        let si = 0usize;
        let mut dropped = false;
        let mut resynced = false;
        for tick in 1..=120u32 {
            em.step_world();
            if !em.due(si, tick) {
                continue;
            }
            em.build_packet(si, tick, false);
            if tick == 40 {
                dropped = true; // this packet is lost on the way to the projector
                continue;
            }
            // a packet that does not match the projector's state is refused: either the
            // decoder notices the changed-set bitmap is about a set we do not hold, or the
            // projector notices the version does not line up.
            let gap = match crate::wire::decode(&em.out, &proj.set) {
                Ok(pkt) => match proj.apply(&pkt, pkt.tick as u64 * TICK_US) {
                    Ok(()) => false,
                    Err(ApplyError::Gap { .. }) => true,
                },
                Err(crate::wire::WireError::Gap) => true,
                Err(e) => panic!("decode: {}", e),
            };
            if gap {
                resynced = true;
                // the emitter answers with a keyframe
                em.build_packet(si, tick, true);
                let kf = crate::wire::decode(&em.out, &proj.set).expect("decode");
                proj.apply(&kf, kf.tick as u64 * TICK_US).expect("keyframe applies");
            }
            for &id in &em.state[si].set {
                let truth = quantise(em.world.pos[id as usize]);
                assert_eq!(proj.pose_at(id, tick), truth, "tick {} id {}", tick, id);
            }
        }
        assert!(dropped && resynced, "the drop should have been detected");
    }

    /// The back-dating is what keeps the delay out of the state: a receiver that anchors at
    /// the packet's tick holds the emitter's truth at that tick, whatever the link did; a
    /// receiver that anchors at the arrival does not.
    #[test]
    fn back_dating_keeps_the_delay_out_of_the_state() {
        let mut em = Emitter::new(99);
        em.mode = Mode::Predictive;
        let mut back = Projector::new();
        back.mode = Mode::Predictive;
        back.backdate = true;
        let mut naive = Projector::new();
        naive.mode = Mode::Predictive;
        naive.backdate = false;
        let si = 0usize;
        // the delay changes from packet to packet, the way a real link's does
        let mut delay_us = 9_000u64;
        let mut naive_errors = 0u64;
        let mut naive_mirror_errors = 0u64;
        for tick in 1..=120u32 {
            em.step_world();
            if !em.due(si, tick) {
                continue;
            }
            delay_us = 3_000 + (delay_us * 7 + 13_331) % 12_000;
            em.build_packet(si, tick, false);
            let pkt = crate::wire::decode(&em.out, &back.set).expect("decode");
            let arrive_us = tick as u64 * TICK_US + delay_us;
            let tick_us = tick as u64 * TICK_US;
            back.apply(&pkt, tick_us).expect("apply");
            naive.apply(&pkt, arrive_us).expect("apply");
            for (k, &id) in em.state[si].set.iter().enumerate() {
                let truth = quantise(em.world.pos[id as usize]);
                // the back-dating receiver reproduces the truth at the packet's tick
                assert_eq!(back.pose_at(id, tick), truth, "tick {} id {}", tick, id);
                // and its held state is the emitter's own state, bit for bit
                assert_eq!(back.objs[k].pos, em.state[si].objs[k].pos, "tick {}", tick);
                assert_eq!(back.objs[k].vel, em.state[si].objs[k].vel, "tick {}", tick);
                assert_eq!(
                    back.objs[k].anchor_us, em.state[si].objs[k].anchor_us,
                    "tick {}", tick
                );
                // the naive receiver does not
                if naive.pose_at(id, tick) != truth {
                    naive_errors += 1;
                }
                if naive.objs[k].anchor_us != em.state[si].objs[k].anchor_us
                    || naive.objs[k].pos != em.state[si].objs[k].pos
                {
                    naive_mirror_errors += 1;
                }
            }
        }
        assert!(
            naive_errors > 0,
            "the naive receiver should not reproduce the truth at the packet's tick"
        );
        assert!(
            naive_mirror_errors > 0,
            "the naive receiver's held state should diverge from the emitter's mirror"
        );
    }

    /// The exit hysteresis: an object that has drifted just outside the region stays in the
    /// subscriber's set, so the region boundary does not churn.
    #[test]
    fn the_exit_hysteresis_holds_a_member_that_drifted_out() {
        let mut em = Emitter::new(4242);
        em.mode = Mode::Predictive;
        let si = 0usize;
        // without hysteresis, count the members that come and go
        let mut churn_without = 0u64;
        let mut churn_with = 0u64;
        let mut em2 = Emitter::new(4242);
        em2.mode = Mode::Predictive;
        em2.hysteresis = 8.0;
        let mut previous: Vec<u32> = Vec::new();
        let mut previous2: Vec<u32> = Vec::new();
        for tick in 1..=900u32 {
            em.step_world();
            em2.step_world();
            em.build_packet(si, tick, false);
            em2.build_packet(si, tick, false);
            let now = em.state[si].set.clone();
            let now2 = em2.state[si].set.clone();
            // the number of members that left the set
            churn_without += now.iter().filter(|id| !previous.contains(id)).count() as u64;
            churn_with += now2.iter().filter(|id| !previous2.contains(id)).count() as u64;
            previous = now;
            previous2 = now2;
        }
        assert!(
            churn_with <= churn_without,
            "the hysteresis should not add churn: {} vs {}",
            churn_with,
            churn_without
        );
        // and it must actually change something, or the test proves nothing
        assert_ne!(
            churn_with, churn_without,
            "the hysteresis made no difference at all"
        );
    }

    /// The 2-byte evict: the leave list travels as absolute 16-bit ids, and the receiver
    /// must read it back the same way.
    #[test]
    fn the_absolute_evicts_round_trip() {
        let mut em = Emitter::new(31337);
        em.mode = Mode::Predictive;
        em.evict_abs = true;
        let mut proj = Projector::new();
        proj.mode = Mode::Predictive;
        let si = 0usize;
        for tick in 1..=200u32 {
            em.step_world();
            if !em.due(si, tick) {
                continue;
            }
            em.build_packet(si, tick, false);
            assert!(em.packet.flags & crate::wire::FLAG_EVICT_ABS != 0);
            let pkt = crate::wire::decode(&em.out, &proj.set).expect("decode");
            proj.apply(&pkt, pkt.tick as u64 * TICK_US).expect("apply");
            for &id in &em.state[si].set {
                let truth = quantise(em.world.pos[id as usize]);
                assert_eq!(proj.pose_at(id, tick), truth, "tick {} id {}", tick, id);
            }
        }
    }
}
