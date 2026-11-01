//! Space: the spatial hash the emitter uses for interest management, the two region shapes,
//! and the subscriber set.

use crate::world::*;

// ------------------------------------------------------------------ grid

/// Uniform spatial hash. Cells hold object ids; an object is re-hashed only when it crosses a
/// cell boundary, so the per-tick maintenance is proportional to the number of movers, not to
/// the number of objects.
pub struct Grid {
    pub cell: f64,
    pub origin: [f64; 3],
    pub dims: [usize; 3],
    cells: Vec<Vec<u32>>,
    slot: Vec<u32>,
    cell_of: Vec<u32>,
}

impl Grid {
    pub fn new(min: [f64; 3], max: [f64; 3], cell: f64, n: usize) -> Grid {
        let mut dims = [0usize; 3];
        for a in 0..3 {
            dims[a] = (((max[a] - min[a]) / cell).ceil() as usize).max(1);
        }
        let n_cells = dims[0] * dims[1] * dims[2];
        Grid {
            cell,
            origin: min,
            dims,
            cells: vec![Vec::new(); n_cells],
            slot: vec![0; n],
            cell_of: vec![u32::MAX; n],
        }
    }

    #[inline]
    fn coord(&self, p: [f64; 3], a: usize) -> usize {
        let x = ((p[a] - self.origin[a]) / self.cell).floor();
        let x = if x < 0.0 {
            0
        } else if x as usize >= self.dims[a] {
            self.dims[a] - 1
        } else {
            x as usize
        };
        x
    }

    #[inline]
    pub fn index(&self, p: [f64; 3]) -> usize {
        let x = self.coord(p, 0);
        let y = self.coord(p, 1);
        let z = self.coord(p, 2);
        (z * self.dims[1] + y) * self.dims[0] + x
    }

    pub fn insert(&mut self, id: u32, p: [f64; 3]) {
        let ci = self.index(p);
        let cell = &mut self.cells[ci];
        self.slot[id as usize] = cell.len() as u32;
        cell.push(id);
        self.cell_of[id as usize] = ci as u32;
    }

    /// Move an object to the cell containing `p` (no-op if it did not cross a boundary).
    pub fn update(&mut self, id: u32, p: [f64; 3]) {
        let ci = self.index(p);
        if self.cell_of[id as usize] == ci as u32 {
            return;
        }
        let old = self.cell_of[id as usize] as usize;
        let s = self.slot[id as usize] as usize;
        let cell = &mut self.cells[old];
        let last = cell.len() - 1;
        cell.swap_remove(s);
        if s < last {
            // the element that used to be last now lives at index s
            self.slot[cell[s] as usize] = s as u32;
        }
        let cell = &mut self.cells[ci];
        self.slot[id as usize] = cell.len() as u32;
        cell.push(id);
        self.cell_of[id as usize] = ci as u32;
    }

    /// Collect the ids of every object in the cells overlapping the box.
    pub fn query_aabb(&self, min: [f64; 3], max: [f64; 3], out: &mut Vec<u32>) {
        let mut lo = [0usize; 3];
        let mut hi = [0usize; 3];
        for a in 0..3 {
            lo[a] = self.coord(min, a);
            hi[a] = self.coord(max, a);
        }
        for z in lo[2]..=hi[2] {
            for y in lo[1]..=hi[1] {
                let base = (z * self.dims[1] + y) * self.dims[0];
                for x in lo[0]..=hi[0] {
                    let cell = &self.cells[base + x];
                    out.extend_from_slice(cell);
                }
            }
        }
    }
}

// ------------------------------------------------------------------ regions

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Shape {
    Sphere,
    Frustum,
}

#[derive(Clone, Copy, Debug)]
pub struct Region {
    pub shape: Shape,
    pub eye: [f64; 3],
    pub radius: f64,
    pub fwd: [f64; 3],
    pub right: [f64; 3],
    pub up: [f64; 3],
    pub tan_h: f64,
    pub tan_v: f64,
    pub near: f64,
    pub far: f64,
}

impl Region {
    #[inline]
    pub fn contains(&self, p: [f64; 3]) -> bool {
        match self.shape {
            Shape::Sphere => {
                let d = p[0] - self.eye[0];
                let d1 = p[1] - self.eye[1];
                let d2 = p[2] - self.eye[2];
                d * d + d1 * d1 + d2 * d2 <= self.radius * self.radius
            }
            Shape::Frustum => {
                let d = [
                    p[0] - self.eye[0],
                    p[1] - self.eye[1],
                    p[2] - self.eye[2],
                ];
                let z = dot(d, self.fwd);
                if z < self.near || z > self.far {
                    return false;
                }
                let x = dot(d, self.right).abs();
                let y = dot(d, self.up).abs();
                x <= z * self.tan_h && y <= z * self.tan_v
            }
        }
    }

    /// Bounding box of the region (used to pick the grid cells to visit).
    pub fn aabb(&self) -> ([f64; 3], [f64; 3]) {
        match self.shape {
            Shape::Sphere => (
                [
                    self.eye[0] - self.radius,
                    self.eye[1] - self.radius,
                    self.eye[2] - self.radius,
                ],
                [
                    self.eye[0] + self.radius,
                    self.eye[1] + self.radius,
                    self.eye[2] + self.radius,
                ],
            ),
            Shape::Frustum => {
                let mut lo = [f64::INFINITY; 3];
                let mut hi = [f64::NEG_INFINITY; 3];
                for &sx in &[-1.0f64, 1.0] {
                    for &sy in &[-1.0f64, 1.0] {
                        for &z in &[self.near, self.far] {
                            let p = [
                                self.eye[0] + self.fwd[0] * z + self.right[0] * sx * z * self.tan_h
                                    + self.up[0] * sy * z * self.tan_v,
                                self.eye[1] + self.fwd[1] * z + self.right[1] * sx * z * self.tan_h
                                    + self.up[1] * sy * z * self.tan_v,
                                self.eye[2] + self.fwd[2] * z + self.right[2] * sx * z * self.tan_h
                                    + self.up[2] * sy * z * self.tan_v,
                            ];
                            for a in 0..3 {
                                if p[a] < lo[a] {
                                    lo[a] = p[a];
                                }
                                if p[a] > hi[a] {
                                    hi[a] = p[a];
                                }
                            }
                        }
                    }
                }
                (lo, hi)
            }
        }
    }
}

// ------------------------------------------------------------------ subscribers

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum PathKind {
    Circle,
    Drift,
    Static,
}

#[derive(Clone, Debug)]
pub struct Subscriber {
    pub id: u32,
    pub shape: Shape,
    pub path: PathKind,
    pub eye0: [f64; 3],
    pub fwd0: [f64; 3],
    pub radius: f64,
    pub tan_h: f64,
    pub tan_v: f64,
    pub near: f64,
    pub far: f64,
    // circle path
    pub path_center: [f64; 3],
    pub path_radius: f64,
    pub path_omega: f64,
    pub path_phase: f64,
    pub path_e1: [f64; 3],
    pub path_e2: [f64; 3],
    // drift path
    pub drift_dir: [f64; 3],
    pub drift_amp: f64,
    pub drift_period: f64,
    pub rate_hz: u32,
    pub join_tick: u32,
    pub interval: u32,
    pub next_due: u32,
    /// Set for the "shared camera" group: those subscribers deliberately overlap.
    pub group: u32,
}

fn tri(x: f64) -> f64 {
    let p = x - x.floor();
    if p < 0.5 {
        4.0 * p - 1.0
    } else {
        3.0 - 4.0 * p
    }
}

impl Subscriber {
    /// The subscriber's region at a given tick.
    pub fn region_at(&self, tick: u32) -> Region {
        let t = tick as f64 * DT;
        let (eye, fwd) = match self.path {
            PathKind::Circle => {
                let th = self.path_omega * t + self.path_phase;
                let (s, c) = (th.sin(), th.cos());
                let eye = [
                    self.path_center[0] + self.path_radius * (c * self.path_e1[0] + s * self.path_e2[0]),
                    self.path_center[1] + self.path_radius * (c * self.path_e1[1] + s * self.path_e2[1]),
                    self.path_center[2] + self.path_radius * (c * self.path_e1[2] + s * self.path_e2[2]),
                ];
                let fwd = [
                    -s * self.path_e1[0] + c * self.path_e2[0],
                    -s * self.path_e1[1] + c * self.path_e2[1],
                    -s * self.path_e1[2] + c * self.path_e2[2],
                ];
                (eye, fwd)
            }
            PathKind::Drift => {
                let k = tri(t / self.drift_period) * self.drift_amp;
                (
                    [
                        self.eye0[0] + self.drift_dir[0] * k,
                        self.eye0[1] + self.drift_dir[1] * k,
                        self.eye0[2] + self.drift_dir[2] * k,
                    ],
                    self.fwd0,
                )
            }
            PathKind::Static => (self.eye0, self.fwd0),
        };
        let up = [0.0, 0.0, 1.0];
        let right_raw = cross(up, fwd);
        let l = norm(right_raw);
        let right = if l < 1e-9 {
            [1.0, 0.0, 0.0]
        } else {
            [right_raw[0] / l, right_raw[1] / l, right_raw[2] / l]
        };
        Region {
            shape: self.shape,
            eye,
            radius: self.radius,
            fwd,
            right,
            up,
            tan_h: self.tan_h,
            tan_v: self.tan_v,
            near: self.near,
            far: self.far,
        }
    }

    /// The subscriber's own eye velocity (m/s), used to express the motion channel in the
    /// subscriber's frame.
    pub fn eye_velocity(&self, tick: u32) -> [f64; 3] {
        let a = self.region_at(tick.saturating_sub(1)).eye;
        let b = self.region_at(tick).eye;
        [
            (b[0] - a[0]) / DT,
            (b[1] - a[1]) / DT,
            (b[2] - a[2]) / DT,
        ]
    }
}

/// Build the 64 subscribers: a mix of spheres and frusta, moving and idle, at different rates,
/// with eight of them deliberately sharing one camera so that regions overlap.
pub fn build_subscribers(seed: u64) -> Vec<Subscriber> {
    let mut rng = Rng::new(seed ^ 0x5DEE_CE66_D000_0001);
    let mut subs: Vec<Subscriber> = Vec::with_capacity(64);

    // Eight subscribers share one camera: the interest regions overlap exactly.
    let shared_eye = [
        rng.range(-40.0, 40.0),
        rng.range(-40.0, 40.0),
        rng.range(-20.0, 20.0),
    ];
    let shared_fwd = {
        let a = rng.range(0.0, std::f64::consts::TAU);
        [a.cos(), a.sin(), 0.0]
    };

    for i in 0..64u32 {
        let sphere = i % 2 == 0;
        let shape = if sphere { Shape::Sphere } else { Shape::Frustum };
        let rate_hz = match i % 8 {
            0 => 60,
            1 => 30,
            2 => 30,
            3 => 20,
            4 => 15,
            5 => 10,
            6 => 5,
            _ => 2,
        };
        let interval = (TICK_HZ / rate_hz).max(1);
        let join_tick = match i {
            60 => 900,
            61 => 1800,
            62 => 2700,
            63 => 3000,
            _ => 0,
        };

        let (eye0, fwd0, radius, tan_h, tan_v, far) = if i < 8 {
            // the shared camera
            (
                shared_eye,
                shared_fwd,
                26.0,
                0.62,
                0.35,
                42.0,
            )
        } else {
            let eye = [
                rng.range(-80.0, 80.0),
                rng.range(-80.0, 80.0),
                rng.range(-40.0, 40.0),
            ];
            let a = rng.range(0.0, std::f64::consts::TAU);
            let fwd = [a.cos(), a.sin(), 0.0];
            let radius = rng.range(14.0, 30.0);
            let tan_v = rng.range(0.35, 0.70);
            let tan_h = tan_v * 16.0 / 9.0;
            let far = rng.range(25.0, 50.0);
            (eye, fwd, radius, tan_h, tan_v, far)
        };

        // path: the shared camera moves in a circle, everyone else mixes circle / drift / idle
        let path = if i < 8 {
            PathKind::Circle
        } else {
            match (i / 3) % 3 {
                0 => PathKind::Circle,
                1 => PathKind::Drift,
                _ => PathKind::Static,
            }
        };

        let (pc, pr, pw, pph, e1, e2) = match path {
            PathKind::Circle => {
                let pc = [
                    rng.range(-60.0, 60.0),
                    rng.range(-60.0, 60.0),
                    rng.range(-30.0, 30.0),
                ];
                let pr = rng.range(15.0, 50.0);
                let speed = rng.range(2.0, 8.0);
                let e1 = {
                    let v = rng.unit();
                    // horizontal component
                    let mut v = v;
                    v[2] = 0.0;
                    let l = norm(v);
                    if l < 1e-6 {
                        [1.0, 0.0, 0.0]
                    } else {
                        [v[0] / l, v[1] / l, v[2] / l]
                    }
                };
                let e2 = [-e1[1], e1[0], 0.0];
                (
                    pc,
                    pr,
                    speed / pr,
                    rng.range(0.0, std::f64::consts::TAU),
                    e1,
                    e2,
                )
            }
            _ => ([0.0; 3], 1.0, 0.0, 0.0, [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
        };

        let drift_dir = {
            let a = rng.range(0.0, std::f64::consts::TAU);
            [a.cos(), a.sin(), 0.0]
        };

        subs.push(Subscriber {
            id: i,
            shape,
            path,
            eye0,
            fwd0,
            radius,
            tan_h,
            tan_v,
            near: 0.5,
            far,
            path_center: pc,
            path_radius: pr,
            path_omega: pw,
            path_phase: pph,
            path_e1: e1,
            path_e2: e2,
            drift_dir,
            drift_amp: rng.range(5.0, 25.0),
            drift_period: rng.range(8.0, 30.0),
            rate_hz,
            join_tick,
            interval,
            // Stagger the first delivery so the emitter's per-tick load stays even.
            next_due: if join_tick == 0 {
                (i % interval).max(1)
            } else {
                join_tick
            },
            group: if i < 8 { 0 } else { i },
        });
    }
    subs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grid_tracks_moving_objects() {
        let mut g = Grid::new(WORLD_MIN, WORLD_MAX, 10.0, 100);
        for i in 0..100u32 {
            g.insert(i, [0.0, 0.0, 0.0]);
        }
        g.update(0, [50.0, 0.0, 0.0]);
        let mut out = Vec::new();
        g.query_aabb([-1.0, -1.0, -1.0], [1.0, 1.0, 1.0], &mut out);
        assert!(!out.contains(&0));
        out.clear();
        g.query_aabb([45.0, -1.0, -1.0], [55.0, 1.0, 1.0], &mut out);
        assert!(out.contains(&0));
        assert_eq!(out.len(), 1);
    }

    #[test]
    fn frustum_contains_only_what_is_in_front() {
        let r = Region {
            shape: Shape::Frustum,
            eye: [0.0, 0.0, 0.0],
            radius: 0.0,
            fwd: [1.0, 0.0, 0.0],
            right: [0.0, 1.0, 0.0],
            up: [0.0, 0.0, 1.0],
            tan_h: 0.5,
            tan_v: 0.5,
            near: 1.0,
            far: 10.0,
        };
        assert!(r.contains([5.0, 0.0, 0.0]));
        assert!(r.contains([5.0, 2.0, 2.0]));
        assert!(!r.contains([-5.0, 0.0, 0.0]));
        assert!(!r.contains([50.0, 0.0, 0.0]));
        assert!(!r.contains([5.0, 4.0, 0.0]));
    }
}
