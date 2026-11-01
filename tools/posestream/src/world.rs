//! The world: 10,000 deterministic objects moving in a fixed arena.
//!
//! The world is a pure function of the seed, so the emitter and the benchmark harness can
//! recompute it exactly. Position is the truth in float metres; the wire carries the quantised
//! (integer) version of it.

pub const TICK_HZ: u32 = 60;
pub const DT: f64 = 1.0 / 60.0;
pub const N_OBJECTS: usize = 10_000;
pub const WORLD_MIN: [f64; 3] = [-100.0, -100.0, -60.0];
pub const WORLD_MAX: [f64; 3] = [100.0, 100.0, 60.0];
/// Position quantum: 1 cm.
pub const Q: f64 = 0.01;
/// Velocity quantum: 1/64 of a position quantum per tick.
pub const VEL_SUB: f64 = 64.0;

// ------------------------------------------------------------------ rng

/// xorshift64* — small, fast, and reproducible.
#[derive(Clone, Copy)]
pub struct Rng(pub u64);

impl Rng {
    pub fn new(seed: u64) -> Rng {
        Rng(seed | 1)
    }
    pub fn next_u64(&mut self) -> u64 {
        let mut x = self.0;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        self.0 = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    }
    /// Uniform in [0,1).
    pub fn f64(&mut self) -> f64 {
        (self.next_u64() >> 11) as f64 * (1.0 / 9_007_199_254_740_992.0)
    }
    pub fn range(&mut self, lo: f64, hi: f64) -> f64 {
        lo + (hi - lo) * self.f64()
    }
    pub fn int(&mut self, n: u64) -> u64 {
        self.next_u64() % n
    }
    /// A unit vector, uniform on the sphere.
    pub fn unit(&mut self) -> [f64; 3] {
        loop {
            let v = [
                self.range(-1.0, 1.0),
                self.range(-1.0, 1.0),
                self.range(-1.0, 1.0),
            ];
            let n = v[0] * v[0] + v[1] * v[1] + v[2] * v[2];
            if n > 1e-6 && n <= 1.0 {
                let s = 1.0 / n.sqrt();
                return [v[0] * s, v[1] * s, v[2] * s];
            }
        }
    }
    /// A unit vector orthogonal to `n`.
    pub fn ortho(&mut self, n: [f64; 3]) -> [f64; 3] {
        let u = self.unit();
        let d = u[0] * n[0] + u[1] * n[1] + u[2] * n[2];
        let mut v = [u[0] - n[0] * d, u[1] - n[1] * d, u[2] - n[2] * d];
        let l = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt();
        if l < 1e-9 {
            return self.ortho(n);
        }
        v = [v[0] / l, v[1] / l, v[2] / l];
        v
    }
}

pub fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

pub fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

pub fn norm(a: [f64; 3]) -> f64 {
    dot(a, a).sqrt()
}

/// Rodrigues' rotation of `v` around the unit axis `k` by `ang` radians.
pub fn rotate(v: [f64; 3], k: [f64; 3], ang: f64) -> [f64; 3] {
    let c = ang.cos();
    let s = ang.sin();
    let kv = cross(k, v);
    let kd = dot(k, v);
    [
        v[0] * c + kv[0] * s + k[0] * kd * (1.0 - c),
        v[1] * c + kv[1] * s + k[1] * kd * (1.0 - c),
        v[2] * c + kv[2] * s + k[2] * kd * (1.0 - c),
    ]
}

// ------------------------------------------------------------------ objects

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Kind {
    Walker,
    Orbiter,
    Fast,
}

pub struct Object {
    pub kind: Kind,
    // walkers and fast movers
    pub dir: [f64; 3],
    pub speed: f64,
    pub epoch_end: u32,
    // orbiters
    pub center: [f64; 3],
    pub u: [f64; 3],
    pub w: [f64; 3],
    pub phase: f64,
    pub omega: f64,
    pub radius: f64,
    pub rng: Rng,
}

const WALKER_EPOCH: u32 = 6;
const FAST_EPOCH: u32 = 3;
/// Maximum heading change per epoch (radians): gentle turns keep the motion predictable.
const MAX_TURN: f64 = 0.22;

impl Object {
    /// Advance one tick. Returns the new position and velocity; the world keeps them in
    /// separate arrays so that the emitter's random lookups stay cache friendly.
    fn advance(&mut self, tick: u32, pos: [f64; 3]) -> ([f64; 3], [f64; 3]) {
        match self.kind {
            Kind::Orbiter => {
                let th = self.omega * (tick as f64) * DT + self.phase;
                let (s, c) = (th.sin(), th.cos());
                let p = [
                    self.center[0] + self.radius * (c * self.u[0] + s * self.w[0]),
                    self.center[1] + self.radius * (c * self.u[1] + s * self.w[1]),
                    self.center[2] + self.radius * (c * self.u[2] + s * self.w[2]),
                ];
                let v = [
                    self.radius * self.omega * (-s * self.u[0] + c * self.w[0]),
                    self.radius * self.omega * (-s * self.u[1] + c * self.w[1]),
                    self.radius * self.omega * (-s * self.u[2] + c * self.w[2]),
                ];
                (p, v)
            }
            Kind::Walker | Kind::Fast => {
                if tick >= self.epoch_end {
                    let axis = self.rng.unit();
                    let ang = self.rng.range(-MAX_TURN, MAX_TURN);
                    self.dir = rotate(self.dir, axis, ang);
                    self.speed = (self.speed * self.rng.range(0.94, 1.06)).clamp(0.3, 42.0);
                    let epoch = if self.kind == Kind::Fast { FAST_EPOCH } else { WALKER_EPOCH };
                    self.epoch_end = tick + epoch;
                }
                let mut p = pos;
                let mut v = [
                    self.dir[0] * self.speed,
                    self.dir[1] * self.speed,
                    self.dir[2] * self.speed,
                ];
                for a in 0..3 {
                    p[a] += v[a] * DT;
                    if p[a] < WORLD_MIN[a] {
                        p[a] = WORLD_MIN[a] + (WORLD_MIN[a] - p[a]);
                        v[a] = -v[a];
                        self.dir[a] = -self.dir[a];
                    } else if p[a] > WORLD_MAX[a] {
                        p[a] = WORLD_MAX[a] - (p[a] - WORLD_MAX[a]);
                        v[a] = -v[a];
                        self.dir[a] = -self.dir[a];
                    }
                }
                (p, v)
            }
        }
    }
}

// ------------------------------------------------------------------ world

pub struct World {
    pub objs: Vec<Object>,
    /// Positions, in a compact array: the emitter looks up arbitrary objects every tick.
    pub pos: Vec<[f64; 3]>,
    pub vel: Vec<[f64; 3]>,
    pub tick: u32,
}

impl World {
    pub fn new(seed: u64) -> World {
        let mut rng = Rng::new(seed ^ 0x9E37_79B9_7F4A_7C15);
        let mut objs = Vec::with_capacity(N_OBJECTS);
        let mut positions: Vec<[f64; 3]> = Vec::with_capacity(N_OBJECTS);
        let mut velocities: Vec<[f64; 3]> = Vec::with_capacity(N_OBJECTS);
        for i in 0..N_OBJECTS {
            let pick = rng.f64();
            let kind = if pick < 0.70 {
                Kind::Walker
            } else if pick < 0.95 {
                Kind::Orbiter
            } else {
                Kind::Fast
            };
            // Per-object stream: the world does not depend on how many objects we generate.
            let mut r = Rng::new(seed
                .wrapping_mul(0xD6E8_FEB8_6659_FD93)
                .wrapping_add((i as u64).wrapping_mul(0xA076_1D64_78BD_642F))
                .wrapping_add(1));
            let (obj, obj_pos) = match kind {
                Kind::Walker | Kind::Fast => {
                    let fast = kind == Kind::Fast;
                    let pos = [
                        r.range(WORLD_MIN[0], WORLD_MAX[0]),
                        r.range(WORLD_MIN[1], WORLD_MAX[1]),
                        r.range(WORLD_MIN[2], WORLD_MAX[2]),
                    ];
                    let speed = if fast {
                        r.range(10.0, 40.0)
                    } else {
                        r.range(0.4, 2.4)
                    };
                    let dir = r.unit();
                    (
                        Object {
                            kind,
                            dir,
                            speed,
                            epoch_end: 0,
                            center: [0.0; 3],
                            u: [0.0; 3],
                            w: [0.0; 3],
                            phase: 0.0,
                            omega: 0.0,
                            radius: 0.0,
                            rng: r,
                        },
                        pos,
                    )
                }
                Kind::Orbiter => {
                    let radius = r.range(5.0, 40.0);
                    let speed = r.range(0.5, 4.0);
                    let omega = speed / radius;
                    let u = r.unit();
                    let w = r.ortho(u);
                    let mut center = [0.0; 3];
                    for a in 0..3 {
                        let lo = WORLD_MIN[a] + radius;
                        let hi = WORLD_MAX[a] - radius;
                        center[a] = if lo < hi { r.range(lo, hi) } else { 0.5 * (WORLD_MIN[a] + WORLD_MAX[a]) };
                    }
                    let phase = r.range(0.0, std::f64::consts::TAU);
                    let mut pos = [0.0; 3];
                    for a in 0..3 {
                        pos[a] = center[a] + radius * (phase.cos() * u[a] + phase.sin() * w[a]);
                    }
                    (
                        Object {
                            kind,
                            dir: [0.0; 3],
                            speed,
                            epoch_end: 0,
                            center,
                            u,
                            w,
                            phase,
                            omega,
                            radius,
                            rng: r,
                        },
                        pos,
                    )
                }
            };
            objs.push(obj);
            positions.push(obj_pos);
            velocities.push([0.0; 3]);
        }
        let mut world = World {
            objs,
            pos: positions,
            vel: velocities,
            tick: 0,
        };
        // the initial velocities follow from the objects themselves
        for i in 0..world.objs.len() {
            world.vel[i] = world.initial_velocity(i);
        }
        world
    }

    fn initial_velocity(&self, i: usize) -> [f64; 3] {
        let o = &self.objs[i];
        match o.kind {
            Kind::Orbiter => {
                let th = o.phase;
                let (s, c) = (th.sin(), th.cos());
                [
                    o.radius * o.omega * (-s * o.u[0] + c * o.w[0]),
                    o.radius * o.omega * (-s * o.u[1] + c * o.w[1]),
                    o.radius * o.omega * (-s * o.u[2] + c * o.w[2]),
                ]
            }
            _ => [o.dir[0] * o.speed, o.dir[1] * o.speed, o.dir[2] * o.speed],
        }
    }

    pub fn step(&mut self) {
        self.tick += 1;
        let tick = self.tick;
        let World { objs, pos, vel, .. } = self;
        for i in 0..objs.len() {
            let (p, v) = objs[i].advance(tick, pos[i]);
            pos[i] = p;
            vel[i] = v;
        }
    }
}

// ------------------------------------------------------------------ quantisation

/// The quantised truth: round(p / Q) per axis.
#[inline]
pub fn quantise(p: [f64; 3]) -> [i32; 3] {
    [
        ((p[0] - WORLD_MIN[0]) / Q).round() as i32,
        ((p[1] - WORLD_MIN[1]) / Q).round() as i32,
        ((p[2] - WORLD_MIN[2]) / Q).round() as i32,
    ]
}

#[inline]
pub fn dequantise(q: [i32; 3]) -> [f64; 3] {
    [
        WORLD_MIN[0] + q[0] as f64 * Q,
        WORLD_MIN[1] + q[1] as f64 * Q,
        WORLD_MIN[2] + q[2] as f64 * Q,
    ]
}

/// Velocity in 1/64 quantum per tick.
#[inline]
pub fn quantise_vel(v: [f64; 3]) -> [i32; 3] {
    [
        (v[0] * DT / Q * VEL_SUB).round() as i32,
        (v[1] * DT / Q * VEL_SUB).round() as i32,
        (v[2] * DT / Q * VEL_SUB).round() as i32,
    ]
}

/// Velocity in m/s from the quantised form.
#[inline]
pub fn dequantise_vel(v: [i32; 3]) -> [f64; 3] {
    let s = Q / (DT * VEL_SUB);
    [v[0] as f64 * s, v[1] as f64 * s, v[2] as f64 * s]
}

/// Displacement in quanta over `dt` ticks for a quantised velocity.
#[inline]
pub fn vel_displacement(v: [i32; 3], dt: i64) -> [i32; 3] {
    [
        ((v[0] as i64 * dt) as f64 / VEL_SUB).round() as i32,
        ((v[1] as i64 * dt) as f64 / VEL_SUB).round() as i32,
        ((v[2] as i64 * dt) as f64 / VEL_SUB).round() as i32,
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn world_is_deterministic() {
        let mut a = World::new(42);
        let mut b = World::new(42);
        for _ in 0..120 {
            a.step();
            b.step();
        }
        for i in 0..N_OBJECTS {
            assert_eq!(a.pos[i], b.pos[i]);
            assert_eq!(a.vel[i], b.vel[i]);
        }
    }

    #[test]
    fn objects_stay_in_the_arena() {
        let mut w = World::new(7);
        for _ in 0..600 {
            w.step();
        }
        for p in &w.pos {
            for a in 0..3 {
                assert!(p[a] >= WORLD_MIN[a] - 1e-6, "axis {} min", a);
                assert!(p[a] <= WORLD_MAX[a] + 1e-6, "axis {} max", a);
            }
        }
    }

    #[test]
    fn quantisation_error_is_within_half_a_quantum() {
        let mut w = World::new(11);
        for _ in 0..300 {
            w.step();
            for i in 0..N_OBJECTS {
                let q = quantise(w.pos[i]);
                let d = dequantise(q);
                for a in 0..3 {
                    assert!((d[a] - w.pos[i][a]).abs() <= Q / 2.0 + 1e-12);
                }
            }
        }
    }

    #[test]
    fn world_has_the_intended_mix() {
        let w = World::new(3);
        let mut walkers = 0;
        let mut orbiters = 0;
        let mut fast = 0;
        for o in &w.objs {
            match o.kind {
                Kind::Walker => walkers += 1,
                Kind::Orbiter => orbiters += 1,
                Kind::Fast => fast += 1,
            }
        }
        assert_eq!(walkers + orbiters + fast, N_OBJECTS);
        assert!(fast > 100 && fast < 1000, "fast movers: {}", fast);
        assert!(orbiters > 1500, "orbiters: {}", orbiters);
    }
}
