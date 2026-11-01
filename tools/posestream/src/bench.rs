//! The benchmark harness: it runs the world, drives the emitter and the projectors, checks
//! every reconstruction against the emitter's ground truth, and produces RESULT.json.

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
}

pub struct Report {
    pub bytes_mean: f64,
    pub bytes_p95: f64,
    pub emitter_p50: f64,
    pub emitter_p95: f64,
    pub latency_p95: f64,
    pub errors: u64,
    pub late_join_resync_ms: f64,
    pub notes: String,
    pub log: String,
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

pub fn run(cfg: &Config) -> Report {
    let n = 64usize;
    let mut em = Emitter::new(cfg.seed);
    em.mode = cfg.mode;
    let mut proj: Vec<Projector> = (0..n).map(|_| Projector::new()).collect();
    for p in proj.iter_mut() {
        p.mode = cfg.mode;
    }

    let mut bytes = vec![0u64; n];
    let mut deliveries = vec![0u64; n];
    let mut keys = vec![0u64; n];
    let mut resyncs = vec![0u64; n];
    let mut objects_seen = vec![0u64; n];

    let mut tick_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
    let mut world_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
    let mut emit_ms: Vec<f64> = Vec::with_capacity(cfg.ticks as usize);
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
    let mut pred = Hist::new();
    // the motion channel expressed in the subscriber's own frame: the apparent motion of
    // every object in the region, which is what a projector renders (or reads as optical flow)
    let mut apparent_sum = 0.0f64;
    let mut apparent_max = 0.0f64;
    let mut apparent_n = 0u64;
    let mut apparent_moving = 0u64;

    let mut late_join_ms: Vec<f64> = Vec::new();
    let mut late_join_e2e: Vec<f64> = Vec::new();
    let drop_resync_ms: Vec<f64> = Vec::new();
    let mut gap_events: Vec<String> = Vec::new();

    // Deterministic packet drops, to exercise the resync path.
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
    let mut digest: u64 = 0xcbf2_9ce4_8422_2325; // FNV-1a

    for tick in 1..=cfg.ticks {
        let t_tick = Instant::now();
        em.step_world();
        let world_end = Instant::now();
        let t_world = world_end.duration_since(t_tick);

        for si in 0..n {
            if !em.due(si, tick) {
                continue;
            }
            let is_late_join = !em.state[si].started;
            let want_key = resync_pending[si] || is_late_join;
            let t_build = Instant::now();
            em.build_packet(si, tick, want_key);
            let _t_built = Instant::now();
            let nbytes = em.out.len();
            bytes_total += nbytes as u64;
            bytes[si] += nbytes as u64;
            deliveries[si] += 1;
            if want_key {
                keys[si] += 1;
                resync_pending[si] = false;
            }
            // byte accounting
            {
                let pk = &em.packet;
                b_header += 22; // magic, flags, eight varints, eight width bytes
                b_enter += pk.enter.len() as u64 * 13;
                b_leave += pk.leave.len() as u64;
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
            }
            for &b in &em.out {
                digest ^= b as u64;
                digest = digest.wrapping_mul(0x1000_0000_01b3);
            }

            // The link: this packet is lost.
            if drops.iter().any(|&(s, t)| s == si as u32 && t == tick) {
                continue;
            }

            let t_dec = Instant::now();
            let pkt = match wire::decode(&em.out, &proj[si].set) {
                Ok(p) => p,
                Err(wire::WireError::Gap) => {
                    // The projector cannot use this packet (its state does not match the
                    // packet's base version): ask the emitter for a keyframe.
                    resync_pending[si] = true;
                    resyncs[si] += 1;
                    gap_events.push(format!(
                        "tick {} sub {}: bitmap base mismatch -> keyframe requested",
                        tick, si
                    ));
                    continue;
                }
                Err(e) => {
                    errors += 1;
                    if error_notes.len() < 8 {
                        error_notes.push(format!("tick {} sub {}: decode error {}", tick, si, e));
                    }
                    continue;
                }
            };
            let t_decoded = Instant::now();
            let applied = proj[si].apply(&pkt);
            let _t_apply = Instant::now();

            match applied {
                Ok(()) => {
                    // The projector must now hold the emitter's ground truth for its region.
                    let st = &em.state[si];
                    if proj[si].set.len() != st.set.len() {
                        errors += 1;
                        if error_notes.len() < 8 {
                            error_notes.push(format!(
                                "tick {} sub {}: set size {} != {}",
                                tick,
                                si,
                                proj[si].set.len(),
                                st.set.len()
                            ));
                        }
                    }
                    objects_seen[si] += st.set.len() as u64;
                    for (i, &id) in st.set.iter().enumerate() {
                        let got = proj[si].set.get(i).copied();
                        if got != Some(id) {
                            errors += 1;
                            continue;
                        }
                        let truth = quantise(em.world.pos[id as usize]);
                        let p = proj[si].pose_at(id, tick);
                        if p != truth {
                            errors += 1;
                            if error_notes.len() < 8 {
                                let o = &em.world.objs[id as usize];
                                let k = st.set.binary_search(&id).unwrap_or(0);
                                let so = st.objs.get(k).copied().unwrap_or_default();
                                let po = proj[si].state_of(id).unwrap_or_default();
                                error_notes.push(format!(
                                    "tick {} sub {} obj {}: {:?} != {:?} | kind {:?} vel {:?} | emitter pos {:?} vel {:?} anchor {:?} tick {} | projector pos {:?} vel {:?} anchor {:?} tick {}",
                                    tick, si, id, p, truth, o.kind, em.world.vel[id as usize],
                                    so.pos, so.vel, so.anchor_vel, so.pos_tick,
                                    po.pos, po.vel, po.anchor_vel, po.pos_tick
                                ));
                            }
                        }
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
                    gap_events.push(format!(
                        "tick {} sub {}: gap (held v{}, offered v{}) -> keyframe requested",
                        tick, si, held, offered
                    ));
                    continue;
                }
            }

            let t_done = Instant::now();
            lat.push(t_done.duration_since(world_end).as_secs_f64() * 1000.0);
            service_lat.push(t_done.duration_since(t_build).as_secs_f64() * 1000.0);
            decode_us.push(t_decoded.duration_since(t_dec).as_secs_f64() * 1e6);

            if is_late_join {
                // Time from the join request to a complete, verified state: the emitter's
                // service of this subscriber (build + encode + decode + apply + check).
                late_join_ms.push(t_done.duration_since(t_build).as_secs_f64() * 1000.0);
                // And the end-to-end figure, which also waits behind the other subscribers
                // served in the same tick.
                late_join_e2e.push(t_done.duration_since(t_tick).as_secs_f64() * 1000.0);
            }
        }

        // Bonus: the motion channel lets a projector predict the poses it has not been told
        // about yet. This is not part of the reconstruction guarantee; it is measured.
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
            for &id in &p.set {
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
            }
        }

        let total = t_tick.elapsed();
        tick_ms.push(total.as_secs_f64() * 1000.0);
        world_ms.push(t_world.as_secs_f64() * 1000.0);
        emit_ms.push((total.as_secs_f64() - t_world.as_secs_f64()) * 1000.0);
    }

    // ---------------------------------------------------------------- report
    let secs = cfg.ticks as f64 / TICK_HZ as f64;
    let per_sub_bytes: Vec<f64> = bytes.iter().map(|&b| b as f64 / secs).collect();
    let mut sorted_bytes = per_sub_bytes.clone();
    sorted_bytes.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let bytes_mean = mean(&per_sub_bytes);
    let bytes_p95 = percentile(&sorted_bytes, 0.95);

    let mut sorted_tick = tick_ms.clone();
    sorted_tick.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let emitter_p50 = percentile(&sorted_tick, 0.50);
    let emitter_p95 = percentile(&sorted_tick, 0.95);

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
        mean(&emit_ms),
        percentile(&sorted_emit, 0.95)
    ));
    log.push_str(&format!(
        "emitter tick total:  p50 {:.3} ms  p95 {:.3} ms  mean {:.3} ms\n",
        emitter_p50,
        emitter_p95,
        mean(&tick_ms)
    ));
    log.push_str(&format!(
        "delivery latency (world committed -> applied): p50 {:.3} ms  p95 {:.3} ms  max {:.3} ms\n",
        percentile(&sorted_lat, 0.50),
        latency_p95,
        sorted_lat.last().copied().unwrap_or(0.0)
    ));
    log.push_str(&format!(
        "subscriber service (build+encode+decode+apply+check): p50 {:.3} ms  p95 {:.3} ms\n",
        percentile(&sorted_service, 0.50),
        percentile(&sorted_service, 0.95)
    ));
    log.push_str(&format!(
        "packet decode:       p50 {:.1} us  p95 {:.1} us\n",
        percentile(&sorted_decode, 0.50),
        percentile(&sorted_decode, 0.95)
    ));
    log.push_str(&format!(
        "bytes: total {} B over {} s = {:.1} kB/s aggregate; per subscriber mean {:.1} B/s, p95 {:.1} B/s\n",
        bytes_total,
        secs,
        bytes_total as f64 / secs / 1000.0,
        bytes_mean,
        bytes_p95
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
        "reconstruction errors: {}   (max |reconstructed - truth| = {:.6} m, bound = {:.6} m per axis)\n",
        errors,
        max_pos_error,
        Q / 2.0
    ));
    log.push_str(&format!(
        "motion-channel prediction between deliveries: p50 {:.6} m  p95 {:.6} m  p99 {:.6} m  max {:.3} m\n",
        pred.q(0.50),
        pred.q(0.95),
        pred.q(0.99),
        pred.max
    ));
    log.push_str(&format!(
        "motion channel in the subscriber's frame: mean apparent speed {:.3} m/s, max {:.3} m/s, \
         {:.1}% of the objects are moving (>5 cm/s)\n",
        if apparent_n > 0 { apparent_sum / apparent_n as f64 } else { 0.0 },
        apparent_max,
        100.0 * apparent_moving as f64 / apparent_n.max(1) as f64
    ));
    log.push_str(&format!(
        "late join resync (service time): {:?} ms\n  (end-to-end behind the same tick's other subscribers: {:?} ms)\n",
        late_join_ms, late_join_e2e
    ));
    if !drop_resync_ms.is_empty() {
        log.push_str(&format!("dropped-packet resync: {:?} ms\n", drop_resync_ms));
    }
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
         quantised truth, never against an accumulated estimate. Deltas travel as biased \
         fixed-width bit fields, one 64-bit word per object, whose width is chosen per axis to \
         minimise the total cost (width times objects plus the escapes); outliers that do not \
         fit escape into a varint list, so a few fast movers cannot widen the field for \
         everybody else. The changed set travels as a bitmap over the subscriber's previous set \
         whenever that is smaller than the id list. The motion channel carries each object's \
         velocity in 1/64 quantum per tick in world coordinates; the projector converts it into \
         its own frame (and into optical flow) locally, which is what lets it interpolate \
         between deliveries. Every packet carries since_version, so a late joiner or a \
         subscriber that lost a packet is detected and resynchronised from a keyframe (the full \
         region with absolute poses), after which it rebuilds the emitter's ground truth \
         exactly. The emitter is single threaded and serves the 64 subscribers on their own \
         cadences (2-60 Hz, staggered, so the load per tick is even); {} delivered states were \
         compared against the ground truth and {} mismatched.",
        objects_seen.iter().sum::<u64>(),
        errors
    );

    Report {
        bytes_mean,
        bytes_p95,
        emitter_p50,
        emitter_p95,
        latency_p95,
        errors,
        late_join_resync_ms,
        notes,
        log,
    }
}

pub fn write_result(path: &str, r: &Report, team: &str) -> std::io::Result<()> {
    let json = format!(
        "{{\n  \"team\": \"{}\",\n  \"bytes_per_s_per_subscriber_mean\": {:.3},\n  \
         \"bytes_per_s_per_subscriber_p95\": {:.3},\n  \"emitter_cpu_ms_per_tick_p50\": {:.4},\n  \
         \"emitter_cpu_ms_per_tick_p95\": {:.4},\n  \"delivery_latency_ms_p95\": {:.4},\n  \
         \"reconstruction_errors\": {},\n  \"quantisation_bound\": \"{}\",\n  \
         \"late_join_resync_ms\": {:.4},\n  \"notes\": \"{}\"\n}}\n",
        team,
        r.bytes_mean,
        r.bytes_p95,
        r.emitter_p50,
        r.emitter_p95,
        r.latency_p95,
        r.errors,
        "5 mm per axis (1 cm position quantum, round-to-nearest); Euclidean <= 8.7 mm; exact \
         against the quantised truth at every delivered tick",
        r.late_join_resync_ms,
        r.notes.replace('"', "'")
    );
    std::fs::write(path, json)
}
