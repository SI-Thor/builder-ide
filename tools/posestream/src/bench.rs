//! The benchmark harness: it runs the world, drives the emitter and the projectors, checks
//! every reconstruction against the emitter's ground truth, and produces RESULT.json.
//!
//! The harness has two shapes, one code path:
//!
//! * the **loopback** (no network): the packet is handed to the receiver with no delay and
//!   no loss. This is the run the winner was measured with, and the new harness reproduces
//!   its bytes exactly.
//! * the **network**: one lossy, delayed link per subscriber (see `net.rs`). The receiver
//!   applies a packet when it arrives, and the referee checks it against the truth *at the
//!   packet's tick*, not at the tick it arrived — that is what "back-dating" means.
//!
//! The referee keeps two numbers apart:
//!
//! * the **reconstruction error**: the projector's pose at the packet's tick, against the
//!   emitter's quantised truth at that tick. This is the bar: zero, within the bound.
//! * the **mirror mismatch**: the projector's held state against the emitter's mirror of
//!   that subscriber's state. This is the state invariant: with back-dating the two are
//!   bit-identical, whatever the link did.

use crate::net::*;
use crate::space::*;
use crate::stream::*;
use crate::wire;
use crate::world::*;
use std::time::Instant;

pub struct Config {
    pub seed: u64,
    pub ticks: u32,
    pub out_path: String,
    pub log_path: String,
    pub mode: Mode,
    pub net: NetConfig,
    /// True: the receiver back-dates the correction (anchors at the packet's tick).
    pub backdate: bool,
    /// The exit hysteresis on the interest regions, in metres.
    pub hysteresis: f64,
    /// Send the leave list as absolute 16-bit ids.
    pub evict_abs: bool,
}

pub struct Report {
    pub bytes_mean: f64,
    pub bytes_p95: f64,
    pub bytes_sent_mean: f64,
    pub emitter_p50: f64,
    pub emitter_p95: f64,
    pub emitter_work_p50: f64,
    pub emitter_work_p95: f64,
    pub latency_p95: f64,
    pub errors: u64,
    pub late_join_resync_ms: f64,
    pub notes: String,
    pub log: String,
    // --- round 2: the network ---
    pub packets_sent: u64,
    pub packets_lost: u64,
    pub packets_delivered: u64,
    pub keyframes: u64,
    pub resyncs: u64,
    pub mirror_mismatches: u64,
    pub max_state_error_mm: f64,
    pub max_reconstruction_error_mm: f64,
    pub max_drift_mm: f64,
    pub drift_over_budget: u64,
    pub drift_checks: u64,
    pub resync_recovery_ms_p95: f64,
    pub reorders: u64,
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let rank = (p * sorted.len() as f64).ceil() as usize;
    let idx = rank.saturating_sub(1).min(sorted.len() - 1);
    sorted[idx]
}

fn mean(v: &[f64]) -> f64 {
    if v.is_empty() {
        return 0.0;
    }
    v.iter().sum::<f64>() / v.len() as f64
}

/// Error histogram with 1 mm bins (the bound is 5 mm, the arena is 200 m).
struct Hist {
    bins: Vec<u64>,
    over: u64,
    max: f64,
}

impl Hist {
    fn new() -> Hist {
        Hist { bins: vec![0; 20_001], over: 0, max: 0.0 }
    }
    fn add(&mut self, e: f64) {
        if e > self.max {
            self.max = e;
        }
        let b = (e * 1000.0).round() as usize;
        if b < self.bins.len() {
            self.bins[b] += 1;
        } else {
            self.over += 1;
        }
    }
    fn q(&self, p: f64) -> f64 {
        let total: u64 = self.bins.iter().sum::<u64>() + self.over;
        if total == 0 {
            return 0.0;
        }
        let target = (p * total as f64).ceil() as u64;
        let mut acc = 0u64;
        for (i, &c) in self.bins.iter().enumerate() {
            acc += c;
            if acc >= target {
                return i as f64 / 1000.0;
            }
        }
        self.max
    }
}

/// The state the emitter sent, kept with the packet so the referee can check a packet that
/// arrives after the world has moved on.
struct Snapshot {
    ids: Vec<u32>,
    /// The quantised truth at the packet's tick.
    truth: Vec<[i32; 3]>,
    /// The emitter's mirror: the truth at each object's last correction.
    mirror_pos: Vec<[i32; 3]>,
    mirror_vel: Vec<[i32; 3]>,
    /// And the time that mirror state refers to.
    mirror_anchor: Vec<u64>,
}

fn snapshot(em: &Emitter, si: usize) -> Snapshot {
    let st = &em.state[si];
    let n = st.set.len();
    let mut ids = Vec::with_capacity(n);
    let mut truth = Vec::with_capacity(n);
    let mut mirror_pos = Vec::with_capacity(n);
    let mut mirror_vel = Vec::with_capacity(n);
    let mut mirror_anchor = Vec::with_capacity(n);
    for (k, &id) in st.set.iter().enumerate() {
        ids.push(id);
        truth.push(quantise(em.world.pos[id as usize]));
        mirror_pos.push(st.objs[k].pos);
        mirror_vel.push(st.objs[k].vel);
        mirror_anchor.push(st.objs[k].anchor_us);
    }
    Snapshot { ids, truth, mirror_pos, mirror_vel, mirror_anchor }
}

/// The index of a kind in the per-kind drift histograms.
fn kind_index(k: Kind) -> usize {
    match k {
        Kind::Walker => 0,
        Kind::Orbiter => 1,
        Kind::Fast => 2,
    }
}

/// The bytes a delta-coded id list costs: the varint length of each difference.
fn varint_len(v: u64) -> u64 {
    let mut n = 1u64;
    let mut v = v >> 7;
    while v != 0 {
        n += 1;
        v >>= 7;
    }
    n
}

pub fn run(cfg: &Config) -> Report {
    let n = 64usize;
    let mut em = Emitter::new(cfg.seed);
    em.mode = cfg.mode;
    em.hysteresis = cfg.hysteresis;
    em.evict_abs = cfg.evict_abs;
    let mut proj: Vec<Projector> = (0..n).map(|_| Projector::new()).collect();
    for p in proj.iter_mut() {
        p.mode = cfg.mode;
        p.backdate = cfg.backdate;
    }
    // one link per subscriber, each with its own random stream
    let mut links: Vec<Link> = (0..n)
        .map(|i| Link::new(cfg.net, cfg.seed ^ (i as u64).wrapping_mul(0x9E37_79B9_7F4A_7C15)))
        .collect();

    let mut bytes = vec![0u64; n]; // delivered
    let mut bytes_sent = vec![0u64; n];
    let mut deliveries = vec![0u64; n];
    let mut keys = vec![0u64; n];
    let mut resyncs = vec![0u64; n];
    let mut objects_seen = vec![0u64; n];

    let mut tick_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
    let mut world_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
    let mut emit_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
    let mut work_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
    let mut lat: Vec<f64> = Vec::with_capacity(cfg.ticks as usize * 32);
    let mut service_lat: Vec<f64> = Vec::with_capacity(cfg.ticks as usize * 32);
    let mut decode_us: Vec<f64> = Vec::with_capacity(cfg.ticks as usize * 32);
    let mut bytes_total: u64 = 0;

    // byte accounting by section
    let mut b_enter: u64 = 0;
    let mut b_leave: u64 = 0;
    let mut b_set: u64 = 0;
    let mut b_escape: u64 = 0;
    let mut b_pos: u64 = 0;
    let mut b_vel: u64 = 0;
    let mut b_mask: u64 = 0;
    let mut b_header: u64 = 0;
    let mut n_changes: u64 = 0;
    let mut n_enters: u64 = 0;
    let mut n_leaves: u64 = 0;

    let mut errors: u64 = 0;
    let mut error_notes: Vec<String> = Vec::new();
    let mut max_pos_error: f64 = 0.0;
    let mut max_reconstruction_error_mm: f64 = 0.0;
    let mut max_state_error_mm: f64 = 0.0;
    let mut mirror_mismatches: u64 = 0;
    let mut pred = Hist::new();
    let mut drift = Hist::new();
    // the drift, per kind of object: the bound is a worst case, these are what happened
    let mut drift_kind: [Hist; 3] = [Hist::new(), Hist::new(), Hist::new()];
    let mut max_drift_mm: f64 = 0.0;
    let mut drift_over_budget: u64 = 0;
    let mut drift_checks: u64 = 0;
    let mut worst_drift_mm: f64 = 0.0;
    let mut worst_drift_case = String::new();
    // the motion channel expressed in the subscriber's own frame
    let mut apparent_sum = 0.0f64;
    let mut apparent_max = 0.0f64;
    let mut apparent_n = 0u64;
    let mut apparent_moving = 0u64;

    let mut late_join_ms: Vec<f64> = Vec::new();
    let mut late_join_e2e: Vec<f64> = Vec::new();
    let mut gap_events: Vec<String> = Vec::new();
    let mut recovery_ms: Vec<f64> = Vec::new();
    let mut keyframes: u64 = 0;
    let mut packets_sent: u64 = 0;
    let mut packets_lost: u64 = 0;
    let mut packets_delivered: u64 = 0;
    // the observed link: the delay range and how many packets were in flight at once
    let mut delay_min_us = u64::MAX;
    let mut delay_max_us = 0u64;
    let mut max_inflight = 0usize;

    // Deterministic packet drops, to exercise the resync path even without a lossy link.
    let mut drop_rng = Rng::new(cfg.seed ^ 0xD0D0_D0D0_D0D0_D0D0);
    let mut drops: Vec<(u32, u32)> = Vec::new();
    for _ in 0..6 {
        let si = drop_rng.int(n as u64) as u32;
        let tk = 600 + drop_rng.int((cfg.ticks as u64).saturating_sub(900).max(1)) as u32;
        if !drops.iter().any(|&(s, t)| s == si && t == tk) {
            drops.push((si, tk));
        }
    }

    let mut resync_pending = vec![false; n];
    // when each subscriber's gap was detected, so the recovery can be timed
    let mut gap_at_us = vec![0u64; n];
    let mut digest: u64 = 0xcbf2_9ce4_8422_2325; // FNV-1a
    let mut arrivals: Vec<InFlight> = Vec::with_capacity(256);

    for tick in 1..=cfg.ticks {
        let t_tick = Instant::now();
        em.step_world();
        let world_end = Instant::now();
        let t_world = world_end.duration_since(t_tick);
        let work_before = em.t_region + em.t_records + em.t_encode;

        for si in 0..n {
            if !em.due(si, tick) {
                continue;
            }
            // has the receiver's resync request reached the emitter?
            if links[si].request_arrived(tick as u64 * TICK_US) {
                resync_pending[si] = true;
            }
            let is_late_join = !em.state[si].started;
            let want_key = resync_pending[si] || is_late_join;
            let t_build = Instant::now();
            em.build_packet(si, tick, want_key);
            let nbytes = em.out.len();
            bytes_total += nbytes as u64;
            bytes_sent[si] += nbytes as u64;
            deliveries[si] += 1;
            packets_sent += 1;
            if want_key {
                keys[si] += 1;
                keyframes += 1;
                resync_pending[si] = false;
            }
            // byte accounting
            {
                let pk = &em.packet;
                b_header += 22; // magic, flags, nine varints, eight width bytes
                b_enter += pk.enter.len() as u64 * 13;
                n_enters += pk.enter.len() as u64;
                n_leaves += pk.leave.len() as u64;
                if pk.flags & wire::FLAG_CHANGE_BITMAP != 0 {
                    b_set += ((pk.n_prev as u64) + 7) / 8;
                } else {
                    b_set += pk.change.len() as u64;
                }
                let mut bits = 0u64;
                let mut vbits = 0u64;
                let mut esc = 0u64;
                for c in &pk.change {
                    bits += 2;
                    if c.has_pos {
                        for a in 0..3 {
                            let w = pk.pos_delta_bits[a] as u32;
                            bits += w as u64;
                            let v = c.dpos[a];
                            let bias = 1i32 << (w - 1);
                            if v < -bias || v > bias - 2 {
                                esc += 1;
                            }
                        }
                    }
                    if c.has_vel {
                        for a in 0..3 {
                            let w = pk.vel_delta_bits[a] as u32;
                            vbits += w as u64;
                            let v = c.dvel[a];
                            let bias = 1i32 << (w - 1);
                            if v < -bias || v > bias - 2 {
                                esc += 1;
                            }
                        }
                    }
                }
                b_mask += (pk.change.len() as u64 * 2) / 8;
                b_pos += (bits - pk.change.len() as u64 * 2) / 8;
                b_vel += vbits / 8;
                b_escape += esc * 2;
                n_changes += pk.change.len() as u64;
                // the leave list: delta-coded varints, or absolute 16-bit evicts
                let mut prev = 0u32;
                for &id in &pk.leave {
                    if pk.flags & wire::FLAG_EVICT_ABS != 0 {
                        b_leave += 2;
                    } else {
                        b_leave += varint_len((id - prev) as u64);
                    }
                    prev = id;
                }
            }
            for &b in &em.out {
                digest ^= b as u64;
                digest = digest.wrapping_mul(0x1000_0000_01b3);
            }

            // The link: the packet is either lost or on its way.
            let deliberate_drop = drops.iter().any(|&(s, t)| s == si as u32 && t == tick);
            if deliberate_drop || links[si].is_lost() {
                packets_lost += 1;
                links[si].lost += 1;
                continue;
            }
            let delay_us = links[si].draw_delay_us();
            if delay_us < delay_min_us {
                delay_min_us = delay_us;
            }
            if delay_us > delay_max_us {
                delay_max_us = delay_us;
            }
            let arrive_us = tick as u64 * TICK_US + delay_us;
            let snap = snapshot(&em, si);
            links[si].send(InFlight {
                bytes: em.out.clone(),
                arrive_us,
                tick,
                emit_wait_ms: t_build.duration_since(world_end).as_secs_f64() * 1000.0,
                build_start: t_build,
                ids: snap.ids,
                truth: snap.truth,
                mirror_pos: snap.mirror_pos,
                mirror_vel: snap.mirror_vel,
                mirror_anchor: snap.mirror_anchor,
            });
        }

        // ---- the receivers apply what has arrived ----
        for si in 0..n {
            // the link's occupancy, before this tick's arrivals are taken off it
            let inflight = links[si].inflight();
            if inflight > max_inflight {
                max_inflight = inflight;
            }
            arrivals.clear();
            // everything that has arrived by the end of this tick
            links[si].drain((tick as u64 + 1) * TICK_US, &mut arrivals);
            for pkt in arrivals.drain(..) {
                packets_delivered += 1;
                bytes[si] += pkt.bytes.len() as u64;
                let t_dec = Instant::now();
                let decoded = wire::decode(&pkt.bytes, &proj[si].set);
                let t_decoded = Instant::now();
                let pkt2 = match decoded {
                    Ok(p) => p,
                    Err(wire::WireError::Gap) => {
                        // The projector cannot use this packet (its state does not match the
                        // packet's base version): ask the emitter for a keyframe.
                        resync_pending[si] = true;
                        resyncs[si] += 1;
                        gap_at_us[si] = pkt.arrive_us;
                        links[si].request(pkt.arrive_us);
                        gap_events.push(format!(
                            "tick {} sub {}: bitmap base mismatch -> keyframe requested",
                            pkt.tick, si
                        ));
                        continue;
                    }
                    Err(e) => {
                        errors += 1;
                        if error_notes.len() < 8 {
                            error_notes.push(format!("tick {} sub {}: decode error {}", pkt.tick, si, e));
                        }
                        continue;
                    }
                };
                // The receiver anchors the correction at the packet's tick when it
                // back-dates, and at the packet's arrival when it does not.
                let anchor_us = if cfg.backdate {
                    pkt.tick as u64 * TICK_US
                } else {
                    pkt.arrive_us
                };
                let was_started = proj[si].started;
                let applied = proj[si].apply(&pkt2, anchor_us);
                let t_applied = Instant::now();
                decode_us.push(t_decoded.duration_since(t_dec).as_secs_f64() * 1e6);

                match applied {
                    Ok(()) => {
                        // The projector must now hold the emitter's state for its region.
                        let snap = &pkt;
                        if proj[si].set.len() != snap.ids.len() {
                            errors += 1;
                            if error_notes.len() < 8 {
                                error_notes.push(format!(
                                    "tick {} sub {}: set size {} != {}",
                                    pkt.tick,
                                    si,
                                    proj[si].set.len(),
                                    snap.ids.len()
                                ));
                            }
                        }
                        objects_seen[si] += snap.ids.len() as u64;
                        for (k, &id) in snap.ids.iter().enumerate() {
                            if proj[si].set.get(k).copied() != Some(id) {
                                errors += 1;
                                continue;
                            }
                            // 1. the reconstruction at the packet's tick, against the truth
                            //    at the packet's tick. This is the bar.
                            let p = proj[si].pose_at(id, pkt.tick);
                            if p != snap.truth[k] {
                                errors += 1;
                                let d = (0..3)
                                    .map(|a| (p[a] - snap.truth[k][a]).abs() as f64 * Q)
                                    .fold(0.0f64, f64::max)
                                    * 1000.0;
                                if d > max_reconstruction_error_mm {
                                    max_reconstruction_error_mm = d;
                                }
                                if error_notes.len() < 8 {
                                    error_notes.push(format!(
                                        "tick {} sub {} obj {}: reconstruction {:?} != truth {:?} ({} mm)",
                                        pkt.tick, si, id, p, snap.truth[k], d
                                    ));
                                }
                            }
                            // 2. the held state, against the emitter's mirror. This is the
                            //    state invariant: the receiver holds exactly what it was told.
                            let mp = proj[si].objs[k].pos;
                            let mv = proj[si].objs[k].vel;
                            let ma = proj[si].objs[k].anchor_us;
                            if mp != snap.mirror_pos[k]
                                || mv != snap.mirror_vel[k]
                                || ma != snap.mirror_anchor[k]
                            {
                                mirror_mismatches += 1;
                                let d = (0..3)
                                    .map(|a| (mp[a] - snap.mirror_pos[k][a]).abs() as f64 * Q)
                                    .fold(0.0f64, f64::max)
                                    * 1000.0;
                                if d > max_state_error_mm {
                                    max_state_error_mm = d;
                                }
                            }
                            // and the error against the float truth, for the bound
                            let d = dequantise(p);
                            let t = em.world.pos[id as usize];
                            for a in 0..3 {
                                let e = (d[a] - t[a]).abs();
                                if e > max_pos_error {
                                    max_pos_error = e;
                                }
                            }
                        }
                    }
                    Err(ApplyError::Gap { held, offered }) => {
                        // A dropped packet: ask the emitter for a keyframe.
                        resync_pending[si] = true;
                        resyncs[si] += 1;
                        gap_at_us[si] = pkt.arrive_us;
                        links[si].request(pkt.arrive_us);
                        gap_events.push(format!(
                            "tick {} sub {}: gap (held v{}, offered v{}) -> keyframe requested",
                            pkt.tick, si, held, offered
                        ));
                        continue;
                    }
                }

                // The delivery latency: the emitter's wait for this subscriber, the link,
                // and the receiver's own service.
                let t_checked = Instant::now();
                let delay_ms =
                    (pkt.arrive_us as f64 - pkt.tick as f64 * TICK_US as f64) / MICROTICKS_PER_MS;
                let service_ms = t_applied.duration_since(t_dec).as_secs_f64() * 1000.0;
                let total_ms = pkt.emit_wait_ms + delay_ms + service_ms;
                lat.push(total_ms);
                service_lat.push(total_ms);

                if was_started == false {
                    // The late-join figure, in the same terms as round 1: the emitter's
                    // service of this subscriber plus the link plus the receiver's decode,
                    // apply and verification.
                    late_join_ms.push(t_checked.duration_since(pkt.build_start).as_secs_f64() * 1000.0);
                    late_join_e2e.push(total_ms);
                }
                // the recovery time of a resync, from the gap to the keyframe's arrival
                if gap_at_us[si] != 0 && pkt2.flags & wire::FLAG_KEYFRAME != 0 {
                    let r = (pkt.arrive_us as f64 - gap_at_us[si] as f64) / MICROTICKS_PER_MS;
                    if r > 0.0 {
                        recovery_ms.push(r);
                    }
                    gap_at_us[si] = 0;
                }
            }
        }

        // Bonus: the motion channel lets a projector predict the poses it has not been told
        // about yet. This is not part of the reconstruction guarantee; it is measured, and
        // it is checked against the drift budget.
        for si in 0..n {
            if tick % 10 == 0 {
                // ... and expressed in the subscriber's frame it is the apparent motion
                let region = em.subs[si].region_at(tick);
                let eye_vel = em.subs[si].eye_velocity(tick);
                for &id in &proj[si].set {
                    let v = proj[si].apparent_velocity(id, &region, eye_vel);
                    let speed = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
                    apparent_sum += speed;
                    apparent_n += 1;
                    if speed > apparent_max {
                        apparent_max = speed;
                    }
                    if speed > 0.05 {
                        apparent_moving += 1;
                    }
                }
            }
            let p = &proj[si];
            if !p.started {
                continue;
            }
            for (k, &id) in p.set.iter().enumerate() {
                let truth = quantise(em.world.pos[id as usize]);
                let pr = p.predicted(id, tick);
                let mut e = 0.0f64;
                for a in 0..3 {
                    let dv = (pr[a] - truth[a]).abs() as f64 * Q;
                    if dv > e {
                        e = dv;
                    }
                }
                pred.add(e);
                // the drift budget: the projection must stay inside the bound the world's
                // motion parameters give for the object's staleness.
                let anchor_tick = (p.objs[k].anchor_us / TICK_US) as u32;
                let s = tick.saturating_sub(anchor_tick);
                let kind = em.world.objs[id as usize].kind;
                let b = crate::budget::drift_bound_m(kind, s);
                drift.add(e);
                drift_kind[kind_index(kind)].add(e);
                if e * 1000.0 > max_drift_mm {
                    max_drift_mm = e * 1000.0;
                }
                drift_checks += 1;
                // an interval that contains a wall reflection has its own bound
                let reflected = em.world.reflect_tick[id as usize] > anchor_tick
                    && em.world.reflect_tick[id as usize] <= tick;
                if e > b && !(reflected && e <= crate::budget::drift_bound_reflect_m(s)) {
                    drift_over_budget += 1;
                    if e * 1000.0 > worst_drift_mm {
                        worst_drift_mm = e * 1000.0;
                        worst_drift_case = format!(
                            "kind {:?} id {} staleness {} ticks, anchor tick {}, last reflection {}, bound {:.3} m, speed {:.2} m/s\n    anchor pos {:?} anchor vel {:?} truth {:?} predicted {:?} anchor_us {} tick {}",
                            kind,
                            id,
                            s,
                            anchor_tick,
                            em.world.reflect_tick[id as usize],
                            b,
                            norm(em.world.vel[id as usize]),
                            p.objs[k].pos,
                            p.objs[k].anchor_vel,
                            truth,
                            pr,
                            p.objs[k].anchor_us,
                            tick
                        );
                    }
                }
            }
        }

        let total = t_tick.elapsed();
        tick_ms.push(total.as_secs_f64() * 1000.0);
        world_ms.push(t_world.as_secs_f64() * 1000.0);
        emit_ms.push((total.as_secs_f64() - t_world.as_secs_f64()) * 1000.0);
        work_ms.push(em.t_region + em.t_records + em.t_encode - work_before);
    }

    // ---------------------------------------------------------------- report
    let secs = cfg.ticks as f64 / TICK_HZ as f64;
    let per_sub_bytes: Vec<f64> = bytes.iter().map(|&b| b as f64 / secs).collect();
    let per_sub_sent: Vec<f64> = bytes_sent.iter().map(|&b| b as f64 / secs).collect();
    let mut sorted_bytes = per_sub_bytes.clone();
    sorted_bytes.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let bytes_mean = mean(&per_sub_bytes);
    let bytes_p95 = percentile(&sorted_bytes, 0.95);
    let bytes_sent_mean = mean(&per_sub_sent);

    let mut sorted_tick = tick_ms.clone();
    sorted_tick.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let emitter_p50 = percentile(&sorted_tick, 0.50);
    let emitter_p95 = percentile(&sorted_tick, 0.95);

    let mut sorted_work = work_ms.clone();
    sorted_work.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let emitter_work_p50 = percentile(&sorted_work, 0.50);
    let emitter_work_p95 = percentile(&sorted_work, 0.95);

    let mut sorted_lat = lat.clone();
    sorted_lat.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let latency_p95 = percentile(&sorted_lat, 0.95);

    let mut sorted_service = service_lat.clone();
    sorted_service.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut sorted_decode = decode_us.clone();
    sorted_decode.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut sorted_world = world_ms.clone();
    sorted_world.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut sorted_emit = emit_ms.clone();
    sorted_emit.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mut sorted_recovery = recovery_ms.clone();
    sorted_recovery.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let resync_recovery_ms_p95 = percentile(&sorted_recovery, 0.95);

    let late_join_resync_ms = late_join_ms.iter().cloned().fold(0.0f64, f64::max);

    // the log
    let mut log = String::new();
    log.push_str("== pose stream benchmark ==\n");
    log.push_str(&format!(
        "seed {}  ticks {}  ({} s at {} Hz)  objects {}  subscribers {}  mode {:?}\n",
        cfg.seed,
        cfg.ticks,
        secs,
        TICK_HZ,
        N_OBJECTS,
        n,
        cfg.mode
    ));
    log.push_str(&format!("network: {}\n", cfg.net.describe()));
    log.push_str(&format!(
        "receiver: back-dating {}\n",
        if cfg.backdate { "on (anchors at the packet's tick)" } else { "off (anchors at the arrival)" }
    ));
    log.push_str(&format!(
        "interest regions: exit hysteresis {} m\nleave list: {}\n",
        cfg.hysteresis,
        if cfg.evict_abs { "absolute 16-bit ids (2-byte evicts)" } else { "delta-coded varints" }
    ));
    log.push_str(&format!(
        "emitter phases (total over the run): region {:.0} ms, records {:.0} ms, encode {:.0} ms\n",
        em.t_region, em.t_records, em.t_encode
    ));
    log.push_str(&format!(
        "world advance:       mean {:.3} ms/tick  p95 {:.3} ms/tick\n",
        mean(&world_ms),
        percentile(&sorted_world, 0.95)
    ));
    log.push_str(&format!(
        "emission:            mean {:.3} ms/tick  p95 {:.3} ms/tick\n",
        mean(&sorted_emit),
        percentile(&sorted_emit, 0.95)
    ));
    log.push_str(&format!(
        "emitter tick total:  p50 {:.3} ms  p95 {:.3} ms  mean {:.3} ms\n",
        emitter_p50,
        emitter_p95,
        mean(&tick_ms)
    ));
    log.push_str(&format!(
        "emitter's own work:  p50 {:.4} ms  p95 {:.4} ms  (region + records + encode)\n",
        emitter_work_p50, emitter_work_p95
    ));
    log.push_str(&format!(
        "delivery latency (link + decode/apply): p50 {:.3} ms  p95 {:.3} ms  max {:.3} ms\n",
        percentile(&sorted_lat, 0.50),
        latency_p95,
        sorted_lat.last().copied().unwrap_or(0.0)
    ));
    log.push_str(&format!(
        "subscriber service (decode + apply): p50 {:.3} ms  p95 {:.3} ms\n",
        percentile(&sorted_service, 0.50),
        percentile(&sorted_service, 0.95)
    ));
    log.push_str(&format!(
        "packet decode:       p50 {:.1} us  p95 {:.1} us\n",
        percentile(&sorted_decode, 0.50),
        percentile(&sorted_decode, 0.95)
    ));
    log.push_str(&format!(
        "link: the delay actually drawn was {:.2} - {:.2} ms (configured {:.2} - {:.2} ms), \
         at most {} packets in flight at once\n",
        delay_min_us as f64 / MICROTICKS_PER_MS,
        delay_max_us as f64 / MICROTICKS_PER_MS,
        cfg.net.min_delay_us() as f64 / MICROTICKS_PER_MS,
        cfg.net.max_delay_us() as f64 / MICROTICKS_PER_MS,
        max_inflight
    ));
    log.push_str(&format!(
        "packets: {} sent, {} lost ({:.2}%), {} delivered\n",
        packets_sent,
        packets_lost,
        100.0 * packets_lost as f64 / packets_sent.max(1) as f64,
        packets_delivered
    ));
    log.push_str(&format!(
        "bytes: delivered {} B over {} s = {:.1} kB/s aggregate; per subscriber mean {:.1} B/s, p95 {:.1} B/s\n",
        bytes.iter().sum::<u64>(),
        secs,
        bytes.iter().sum::<u64>() as f64 / secs / 1000.0,
        bytes_mean,
        bytes_p95
    ));
    log.push_str(&format!(
        "bytes on the wire:   per subscriber mean {:.1} B/s (the difference is what the link lost)\n",
        bytes_sent_mean
    ));
    log.push_str(&format!(
        "byte breakdown (approx): header {:.1}%  enter {:.1}%  leave {:.1}%  changed-set {:.1}%  \
         pos deltas {:.1}%  vel deltas {:.1}%  masks {:.1}%  escapes {:.1}%\n",
        100.0 * b_header as f64 / bytes_total as f64,
        100.0 * b_enter as f64 / bytes_total as f64,
        100.0 * b_leave as f64 / bytes_total as f64,
        100.0 * b_set as f64 / bytes_total as f64,
        100.0 * b_pos as f64 / bytes_total as f64,
        100.0 * b_vel as f64 / bytes_total as f64,
        100.0 * b_mask as f64 / bytes_total as f64,
        100.0 * b_escape as f64 / bytes_total as f64
    ));
    log.push_str(&format!(
        "objects carried: {} enters, {} leaves, {} change records ({} delivered states)\n",
        n_enters,
        n_leaves,
        n_changes,
        objects_seen.iter().sum::<u64>()
    ));
    log.push_str(&format!(
        "reconstruction errors: {}   (max |reconstructed - truth| = {:.6} m, bound = {:.6} m per axis; \
         worst reconstruction error {:.1} mm)\n",
        errors,
        max_pos_error,
        Q / 2.0,
        max_reconstruction_error_mm
    ));
    log.push_str(&format!(
        "mirror mismatches: {} (the receiver's held state against the emitter's mirror; worst {:.1} mm)\n",
        mirror_mismatches, max_state_error_mm
    ));
    log.push_str(&format!(
        "resyncs: {} gap(s), {} keyframe(s); recovery from the gap to the keyframe's arrival: \
         p50 {:.1} ms  p95 {:.1} ms  max {:.1} ms\n",
        resyncs.iter().sum::<u64>(),
        keyframes,
        percentile(&sorted_recovery, 0.50),
        resync_recovery_ms_p95,
        sorted_recovery.last().copied().unwrap_or(0.0)
    ));
    log.push_str(&format!(
        "motion-channel prediction between deliveries: p50 {:.6} m  p95 {:.6} m  p99 {:.6} m  max {:.3} m\n",
        pred.q(0.50),
        pred.q(0.95),
        pred.q(0.99),
        pred.max
    ));
    log.push_str("the drift budget, by delivery interval (the bound the world's motion parameters give):\n");
    for (s, orb, walk, fast) in crate::budget::tier_table(&[1, 2, 3, 4, 6, 12, 30]) {
        log.push_str(&format!(
            "  every {:2} ticks: orbiter {:8.3} m   walker {:8.3} m   fast mover {:8.3} m\n",
            s, orb, walk, fast
        ));
    }
    log.push_str(&format!(
        "drift by kind: walker p50 {:.1} mm p95 {:.1} mm max {:.1} mm | orbiter p50 {:.1} mm p95 {:.1} mm max {:.1} mm | fast p50 {:.1} mm p95 {:.1} mm max {:.1} mm\n",
        drift_kind[0].q(0.50) * 1000.0, drift_kind[0].q(0.95) * 1000.0, drift_kind[0].max * 1000.0,
        drift_kind[1].q(0.50) * 1000.0, drift_kind[1].q(0.95) * 1000.0, drift_kind[1].max * 1000.0,
        drift_kind[2].q(0.50) * 1000.0, drift_kind[2].q(0.95) * 1000.0, drift_kind[2].max * 1000.0,
    ));
    log.push_str(&format!(
        "drift against the budget: {} checks, worst {:.1} mm, {} over the bound\n  worst over: {}\n",
        drift_checks,
        max_drift_mm,
        drift_over_budget,
        worst_drift_case
    ));
    log.push_str(&format!(
        "motion channel in the subscriber's frame: mean apparent speed {:.3} m/s, max {:.3} m/s, \
         {:.1}% of the objects are moving (>5 cm/s)\n",
        if apparent_n > 0 { apparent_sum / apparent_n as f64 } else { 0.0 },
        apparent_max,
        100.0 * apparent_moving as f64 / apparent_n.max(1) as f64
    ));
    log.push_str(&format!(
        "late join resync (service time + link): {:?} ms\n",
        late_join_ms
    ));
    for g in &gap_events {
        log.push_str(&format!("  {}\n", g));
    }
    for e in &error_notes {
        log.push_str(&format!("  ERROR {}\n", e));
    }
    log.push_str(&format!("stream digest (fnv1a over all delivered bytes): {:#018x}\n", digest));
    log.push('\n');
    log.push_str("id  shape  path    rate  region  deliveries  keyframes  resyncs  bytes/s   camera\n");
    for si in 0..n {
        let s = &em.subs[si];
        let shape = if s.shape == Shape::Sphere { "sphere" } else { "frustum" };
        let path = match s.path {
            PathKind::Circle => "circle",
            PathKind::Drift => "drift",
            PathKind::Static => "idle",
        };
        let group = if s.group == 0 { "shared" } else { "" };
        log.push_str(&format!(
            "{:2}  {}  {}  {:3} Hz  {:5}   {:9}  {:8}  {:7}  {:8.1}  {}\n",
            s.id,
            shape,
            path,
            s.rate_hz,
            em.state[si].set.len(),
            deliveries[si],
            keys[si],
            resyncs[si],
            per_sub_bytes[si],
            group
        ));
    }

    let notes = format!(
        "The emitter owns the canon (10,000 seeded objects: random walks, circular orbits and a \
         few fast movers) and a 10 m spatial hash, and it is viewpoint-agnostic: it knows each \
         subscriber's interest region, not its camera. At every delivery it intersects the \
         subscriber's moving region (a sphere or a perspective frustum) with the hash and sends \
         only the difference from what that subscriber already holds: objects that entered the \
         region (absolute quantised pose), objects that left (id only), and objects whose pose \
         moved (a quantised delta). The pose delta is measured against what the projector can \
         *predict* from the motion channel it already holds - a snapshot of position, velocity \
         and time, extrapolated - so an object moving smoothly costs nothing at all, and the \
         projector applies the identical prediction, so the two agree exactly. Positions are \
         quantised to a 1 cm grid (round-to-nearest): a reconstruction is off by at most 5 mm \
         per axis (8.7 mm Euclidean) and never drifts, because every delta is taken against the \
         quantised truth, never against an accumulated estimate. Network: {}. The receiver \
         back-dates: it anchors each correction at the tick the correction was computed for, so \
         the held state is the emitter's truth at that tick whatever the link did, and the \
         reconstruction is checked against the truth at the packet's tick, not at the tick the \
         packet arrived. {} delivered states were compared against the ground truth and {} \
         mismatched; {} mirror mismatches.",
        cfg.net.describe(),
        objects_seen.iter().sum::<u64>(),
        errors,
        mirror_mismatches
    );

    Report {
        bytes_mean,
        bytes_p95,
        bytes_sent_mean,
        emitter_p50,
        emitter_p95,
        emitter_work_p50,
        emitter_work_p95,
        latency_p95,
        errors,
        late_join_resync_ms,
        notes,
        log,
        packets_sent,
        packets_lost,
        packets_delivered,
        keyframes,
        resyncs: resyncs.iter().sum(),
        mirror_mismatches,
        max_state_error_mm,
        max_reconstruction_error_mm,
        max_drift_mm,
        drift_over_budget,
        drift_checks,
        resync_recovery_ms_p95,
        reorders: links.iter().map(|l| l.reorderings).sum(),
    }
}

pub fn write_result(path: &str, r: &Report, team: &str, cfg: &Config) -> std::io::Result<()> {
    let json = format!(
        "{{\n  \"team\": \"{}\",\n  \"bytes_per_s_per_subscriber_mean\": {:.3},\n  \
         \"bytes_per_s_per_subscriber_p95\": {:.3},\n  \
         \"bytes_per_s_per_subscriber_sent_mean\": {:.3},\n  \
         \"emitter_cpu_ms_per_tick_p50\": {:.4},\n  \
         \"emitter_cpu_ms_per_tick_p95\": {:.4},\n  \
         \"emitter_work_ms_per_tick_p50\": {:.4},\n  \
         \"emitter_work_ms_per_tick_p95\": {:.4},\n  \
         \"delivery_latency_ms_p95\": {:.4},\n  \
         \"reconstruction_errors\": {},\n  \
         \"quantisation_bound\": \"{}\",\n  \
         \"late_join_resync_ms\": {:.4},\n  \
         \"network\": \"{}\",\n  \
         \"packets_sent\": {},\n  \"packets_lost\": {},\n  \"packets_delivered\": {},\n  \
         \"keyframes\": {},\n  \"resyncs\": {},\n  \
         \"resync_recovery_ms_p95\": {:.4},\n  \
         \"mirror_mismatches\": {},\n  \
         \"max_reconstruction_error_mm\": {:.3},\n  \
         \"max_state_divergence_mm\": {:.3},\n  \
         \"max_drift_mm\": {:.3},\n  \
         \"drift_over_budget\": {},\n  \
         \"drift_checks\": {},\n  \
         \"packets_reordered\": {},\n  \
         \"notes\": \"{}\"\n}}\n",
        team,
        r.bytes_mean,
        r.bytes_p95,
        r.bytes_sent_mean,
        r.emitter_p50,
        r.emitter_p95,
        r.emitter_work_p50,
        r.emitter_work_p95,
        r.latency_p95,
        r.errors,
        "5 mm per axis (1 cm position quantum, round-to-nearest); Euclidean <= 8.7 mm; exact \
         against the quantised truth at every delivered tick",
        r.late_join_resync_ms,
        cfg.net.describe().replace('"', "'"),
        r.packets_sent,
        r.packets_lost,
        r.packets_delivered,
        r.keyframes,
        r.resyncs,
        r.resync_recovery_ms_p95,
        r.mirror_mismatches,
        r.max_reconstruction_error_mm,
        r.max_state_error_mm,
        r.max_drift_mm,
        r.drift_over_budget,
        r.drift_checks,
        r.reorders,
        r.notes.replace('"', "'")
    );
    std::fs::write(path, json)
}
