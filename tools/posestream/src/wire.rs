//! Wire format for the pose stream.
//!
//! One packet per subscriber per delivery. Everything is little-endian; bit-packed fields are
//! LSB-first inside a byte. Deltas are *biased* fixed-width fields: for a width `w` the value
//! `v` is stored as `u = v + 2^(w-1)`; the all-ones pattern `2^w-1` is reserved as an escape
//! marker and the real value travels in the packet's escape list as a zigzag varint. That way
//! one fast mover cannot inflate the field width for every other object in the packet.

pub const MAGIC: u8 = 0xA1;
pub const FLAG_KEYFRAME: u8 = 0x01;
pub const FLAG_CHANGE_BITMAP: u8 = 0x02;
pub const FLAG_VELOCITY: u8 = 0x04;

/// Absolute positions are unsigned 16-bit (the arena is 200 m / 1 cm = 20000 quanta).
pub const POS_ABS_BITS: u8 = 16;
/// Absolute velocities are 16-bit biased (velocity quantum = 1/64 quantum per tick).
pub const VEL_ABS_BITS: u8 = 16;
pub const VEL_BIAS: i32 = 1 << 15;

#[derive(Debug)]
pub enum WireError {
    Truncated,
    BadVarint,
    BadMagic,
    BadFlags,
    EscapeUnderflow,
    /// The packet's changed-set bitmap is indexed against a previous set this reader does not
    /// hold: the reader is out of sync and must ask for a keyframe.
    Gap,
}

impl std::fmt::Display for WireError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self)
    }
}

// ---------------------------------------------------------------- bit writer

pub struct BitWriter<'a> {
    buf: &'a mut Vec<u8>,
    acc: u64,
    n: u32,
}

impl<'a> BitWriter<'a> {
    pub fn new(buf: &'a mut Vec<u8>) -> Self {
        BitWriter { buf, acc: 0, n: 0 }
    }

    #[inline]
    fn mask(w: u32) -> u64 {
        if w >= 64 {
            u64::MAX
        } else {
            (1u64 << w) - 1
        }
    }

    /// Write `w` low bits of `v` (LSB-first).
    #[inline]
    pub fn bits(&mut self, v: u64, w: u32) {
        if w == 0 {
            return;
        }
        debug_assert!(w <= 64);
        // keep the accumulator from overflowing
        while self.n + w > 64 {
            self.buf.push((self.acc & 0xFF) as u8);
            self.acc >>= 8;
            self.n -= 8;
        }
        self.acc |= (v & Self::mask(w)) << self.n;
        self.n += w;
        if self.n >= 32 {
            let b = (self.acc as u32).to_le_bytes();
            self.buf.extend_from_slice(&b);
            self.acc >>= 32;
            self.n -= 32;
        }
    }

    /// Pad to the next byte boundary.
    pub fn align(&mut self) {
        while self.n >= 8 {
            self.buf.push((self.acc & 0xFF) as u8);
            self.acc >>= 8;
            self.n -= 8;
        }
        if self.n > 0 {
            self.buf.push((self.acc & 0xFF) as u8);
            self.acc = 0;
            self.n = 0;
        }
    }

    /// LEB128 varint. Byte aligned: call `align()` first if bit fields were written.
    pub fn varint(&mut self, mut v: u64) {
        self.align();
        loop {
            let b = (v & 0x7F) as u8;
            v >>= 7;
            if v == 0 {
                self.buf.push(b);
                break;
            } else {
                self.buf.push(b | 0x80);
            }
        }
    }

    pub fn svarint(&mut self, v: i64) {
        self.varint(((v << 1) ^ (v >> 63)) as u64);
    }

    pub fn finish(mut self) {
        self.align();
    }
}

// ---------------------------------------------------------------- bit reader

pub struct BitReader<'a> {
    buf: &'a [u8],
    pos: usize,
    acc: u64,
    n: u32,
}

impl<'a> BitReader<'a> {
    pub fn new(buf: &'a [u8]) -> Self {
        BitReader { buf, pos: 0, acc: 0, n: 0 }
    }

    fn need(&mut self, n: usize) -> Result<(), WireError> {
        if self.pos + n > self.buf.len() {
            Err(WireError::Truncated)
        } else {
            Ok(())
        }
    }

    #[inline]
    fn mask(w: u32) -> u64 {
        if w >= 64 {
            u64::MAX
        } else {
            (1u64 << w) - 1
        }
    }

    pub fn bits(&mut self, w: u32) -> Result<u64, WireError> {
        if w == 0 {
            return Ok(0);
        }
        while self.n < w {
            self.need(1)?;
            self.acc |= (self.buf[self.pos] as u64) << self.n;
            self.pos += 1;
            self.n += 8;
        }
        let v = self.acc & Self::mask(w);
        self.acc >>= w;
        self.n -= w;
        Ok(v)
    }

    pub fn align(&mut self) {
        if self.n > 0 {
            self.acc >>= self.n;
            self.n = 0;
        }
    }

    pub fn varint(&mut self) -> Result<u64, WireError> {
        let mut v: u64 = 0;
        let mut shift = 0u32;
        loop {
            self.need(1)?;
            let b = self.buf[self.pos];
            self.pos += 1;
            v |= ((b & 0x7F) as u64) << shift;
            if b & 0x80 == 0 {
                break;
            }
            shift += 7;
            if shift > 63 {
                return Err(WireError::BadVarint);
            }
        }
        Ok(v)
    }

    pub fn svarint(&mut self) -> Result<i64, WireError> {
        let v = self.varint()?;
        Ok(((v >> 1) as i64) ^ -((v & 1) as i64))
    }
}

// ---------------------------------------------------------------- packet model

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EnterRec {
    pub id: u32,
    /// Absolute quantised position.
    pub pos: [u16; 3],
    /// Absolute quantised velocity, in 1/64 quantum per tick.
    pub vel: [i16; 3],
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ChangeRec {
    pub id: u32,
    /// Position delta, in quanta, relative to the last value sent for this object.
    pub dpos: [i32; 3],
    /// Velocity delta, in 1/64 quantum per tick, relative to the last value sent.
    pub dvel: [i32; 3],
    pub has_pos: bool,
    pub has_vel: bool,
}

#[derive(Clone, Debug, Default)]
pub struct Packet {
    pub flags: u8,
    pub tick: u32,
    pub since_version: u32,
    /// Objects in the subscriber's region at `tick`.
    pub n_region: u32,
    /// Size of the subscriber's previous set (the bitmap's domain).
    pub n_prev: u32,
    pub enter: Vec<EnterRec>,
    pub leave: Vec<u32>,
    pub change: Vec<ChangeRec>,
    /// Changed-set bitmap over the previous set (if FLAG_CHANGE_BITMAP).
    pub bitmap: Vec<u8>,
    pub pos_delta_bits: [u8; 3],
    pub vel_delta_bits: [u8; 3],
}

#[inline]
fn bias(w: u8) -> i32 {
    1i32 << (w - 1)
}

/// Is `v` representable in a biased `w`-bit field without hitting the escape marker?
#[inline]
fn in_band(v: i32, w: u8) -> bool {
    let b = bias(w);
    v >= -b && v <= b - 2
}

/// Bytes a zigzag varint needs for the largest magnitude of a bit-length bucket.
fn varint_bytes_for_bits(b: usize) -> u32 {
    let z = 2u64 * ((1u64 << b) - 1);
    let bits = 64 - z.leading_zeros();
    ((bits + 6) / 7).max(1) as u32
}

/// Pick the width that minimises the total cost of the field: every delta costs `w` bits, and
/// every delta that does not fit costs an extra varint in the escape list. A histogram of the
/// magnitudes' bit lengths is enough to price every candidate width.
fn best_width(mags: &[u32]) -> u8 {
    if mags.is_empty() {
        return 3;
    }
    let n = mags.len() as u64;
    let mut hist = [0u64; 33];
    for &m in mags {
        hist[(32 - m.leading_zeros()) as usize] += 1;
    }
    // above[b] = the number of magnitudes whose bit length is greater than b
    let mut above = [0u64; 34];
    for b in (0..32).rev() {
        above[b] = above[b + 1] + hist[b + 1];
    }
    let mut best_w = 3u8;
    let mut best_cost = u64::MAX;
    for w in 3u8..=24 {
        let threshold = (1u64 << (w - 1)) - 2;
        let tbits = (64 - threshold.leading_zeros()) as usize;
        let mut esc_bits = 0u64;
        for b in (tbits + 1)..=32 {
            esc_bits += hist[b] * varint_bytes_for_bits(b) as u64 * 8;
        }
        let cost = n * w as u64 + esc_bits;
        if cost < best_cost {
            best_cost = cost;
            best_w = w;
        }
    }
    best_w
}

/// Reusable buffers for the encoder, so a packet costs no allocation.
#[derive(Default)]
pub struct EncodeScratch {
    mags: Vec<u32>,
    escapes: Vec<i32>,
}

fn signed_from_biased(u: u64, w: u8) -> i32 {
    let b = bias(w) as i64;
    (u as i64 - b) as i32
}

// ---------------------------------------------------------------- encoder

pub fn encode(pkt: &mut Packet, out: &mut Vec<u8>, scratch: &mut EncodeScratch) {
    // Field widths: choose the width that minimises the total cost, so a handful of fast
    // movers do not widen the field for everybody else.
    let mut pos_bits = [3u8; 3];
    let mut vel_bits = [3u8; 3];
    for axis in 0..3 {
        scratch.mags.clear();
        for c in pkt.change.iter() {
            if c.has_pos {
                scratch.mags.push(c.dpos[axis].unsigned_abs());
            }
        }
        pos_bits[axis] = best_width(&scratch.mags);
    }
    for axis in 0..3 {
        scratch.mags.clear();
        for c in pkt.change.iter() {
            if c.has_vel {
                scratch.mags.push(c.dvel[axis].unsigned_abs());
            }
        }
        vel_bits[axis] = best_width(&scratch.mags);
    }
    // publish the chosen widths so the caller can reason about the packet
    pkt.pos_delta_bits = pos_bits;
    pkt.vel_delta_bits = vel_bits;

    // Escape list, in traversal order (record: pos axes, then vel axes).
    scratch.escapes.clear();
    for c in pkt.change.iter() {
        if c.has_pos {
            for axis in 0..3 {
                if !in_band(c.dpos[axis], pos_bits[axis]) {
                    scratch.escapes.push(c.dpos[axis]);
                }
            }
        }
        if c.has_vel {
            for axis in 0..3 {
                if !in_band(c.dvel[axis], vel_bits[axis]) {
                    scratch.escapes.push(c.dvel[axis]);
                }
            }
        }
    }

    let mut w = BitWriter::new(out);
    w.buf.push(MAGIC);
    w.buf.push(pkt.flags);
    w.varint(pkt.tick as u64);
    w.varint(pkt.since_version as u64);
    w.varint(pkt.n_region as u64);
    w.varint(pkt.enter.len() as u64);
    w.varint(pkt.leave.len() as u64);
    w.varint(pkt.change.len() as u64);
    w.varint(pkt.n_prev as u64);
    w.varint(scratch.escapes.len() as u64);
    w.buf.push(POS_ABS_BITS);
    w.buf.push(VEL_ABS_BITS);
    w.buf.extend_from_slice(&pos_bits);
    w.buf.extend_from_slice(&vel_bits);

    // Enter ids (delta coded, ascending).
    let mut prev: u32 = 0;
    for e in &pkt.enter {
        w.varint((e.id - prev) as u64);
        prev = e.id;
    }
    // Leave ids (delta coded, ascending).
    let mut prev = 0u32;
    for id in &pkt.leave {
        w.varint((*id - prev) as u64);
        prev = *id;
    }
    // Changed set: bitmap over the previous set, or delta-coded ids.
    if pkt.flags & FLAG_CHANGE_BITMAP != 0 {
        w.buf.extend_from_slice(&pkt.bitmap);
    } else {
        let mut prev = 0u32;
        for c in &pkt.change {
            w.varint((c.id - prev) as u64);
            prev = c.id;
        }
    }
    // Escape list.
    for e in &scratch.escapes {
        w.svarint(*e as i64);
    }

    // Bit-packed section.
    w.align();
    for e in &pkt.enter {
        // the three axes of a pose fit in one 64 bit word
        let mut p = 0u64;
        for axis in 0..3 {
            p |= (e.pos[axis] as u64) << (axis * POS_ABS_BITS as usize);
        }
        w.bits(p, POS_ABS_BITS as u32 * 3);
        if pkt.flags & FLAG_VELOCITY != 0 {
            let mut v = 0u64;
            for axis in 0..3 {
                v |= ((e.vel[axis] as i32 + VEL_BIAS) as u64) << (axis * VEL_ABS_BITS as usize);
            }
            w.bits(v, VEL_ABS_BITS as u32 * 3);
        }
    }
    for c in &pkt.change {
        let mut mask = 0u64;
        let mut total = 2u32;
        if c.has_pos {
            mask |= 1;
            total += pos_bits[0] as u32 + pos_bits[1] as u32 + pos_bits[2] as u32;
        }
        if c.has_vel {
            mask |= 2;
            total += vel_bits[0] as u32 + vel_bits[1] as u32 + vel_bits[2] as u32;
        }
        if total <= 64 {
            // one word per record: the mask, then the three axes of each field
            let mut packed = mask;
            let mut shift = 2u32;
            if c.has_pos {
                for axis in 0..3 {
                    let width = pos_bits[axis];
                    let v = c.dpos[axis];
                    let u = if in_band(v, width) {
                        (v + bias(width)) as u64
                    } else {
                        (1u64 << width) - 1
                    };
                    packed |= u << shift;
                    shift += width as u32;
                }
            }
            if c.has_vel {
                for axis in 0..3 {
                    let width = vel_bits[axis];
                    let v = c.dvel[axis];
                    let u = if in_band(v, width) {
                        (v + bias(width)) as u64
                    } else {
                        (1u64 << width) - 1
                    };
                    packed |= u << shift;
                    shift += width as u32;
                }
            }
            w.bits(packed, total);
        } else {
            w.bits(mask, 2);
            if c.has_pos {
                for axis in 0..3 {
                    let width = pos_bits[axis];
                    let v = c.dpos[axis];
                    if in_band(v, width) {
                        w.bits((v + bias(width)) as u64, width as u32);
                    } else {
                        w.bits((1u64 << width) - 1, width as u32);
                    }
                }
            }
            if c.has_vel {
                for axis in 0..3 {
                    let width = vel_bits[axis];
                    let v = c.dvel[axis];
                    if in_band(v, width) {
                        w.bits((v + bias(width)) as u64, width as u32);
                    } else {
                        w.bits((1u64 << width) - 1, width as u32);
                    }
                }
            }
        }
    }
    w.finish();
}

// ---------------------------------------------------------------- decoder

/// Decode a packet. `prev_ids` is the subscriber's previous object set (ascending ids); it is
/// the domain of the changed-set bitmap, so a bitmap packet can only be decoded by a projector
/// that holds the matching previous state.
pub fn decode(buf: &[u8], prev_ids: &[u32]) -> Result<Packet, WireError> {
    let mut r = BitReader::new(buf);
    if buf.len() < 2 || buf[0] != MAGIC {
        return Err(WireError::BadMagic);
    }
    let flags = buf[1];
    if flags & !(FLAG_KEYFRAME | FLAG_CHANGE_BITMAP | FLAG_VELOCITY) != 0 {
        return Err(WireError::BadFlags);
    }
    r.pos = 2; // skip magic + flags
    let tick = r.varint()? as u32;
    let since_version = r.varint()? as u32;
    let n_region = r.varint()? as u32;
    let n_enter = r.varint()? as usize;
    let n_leave = r.varint()? as usize;
    let n_change = r.varint()? as usize;
    let n_prev = r.varint()? as u32;
    let n_escape = r.varint()? as usize;
    r.need(2 + 6)?;
    r.pos += 2; // POS_ABS_BITS, VEL_ABS_BITS
    let mut pos_delta_bits = [0u8; 3];
    let mut vel_delta_bits = [0u8; 3];
    pos_delta_bits.copy_from_slice(&buf[r.pos..r.pos + 3]);
    vel_delta_bits.copy_from_slice(&buf[r.pos + 3..r.pos + 6]);
    r.pos += 6;

    let mut enter = Vec::with_capacity(n_enter);
    let mut prev = 0u32;
    for _ in 0..n_enter {
        let d = r.varint()? as u32;
        prev = prev.wrapping_add(d);
        enter.push(EnterRec { id: prev, pos: [0; 3], vel: [0; 3] });
    }
    let mut leave = Vec::with_capacity(n_leave);
    let mut prev = 0u32;
    for _ in 0..n_leave {
        let d = r.varint()? as u32;
        prev = prev.wrapping_add(d);
        leave.push(prev);
    }

    let mut bitmap = Vec::new();
    let mut change_ids: Vec<u32> = Vec::new();
    if flags & FLAG_CHANGE_BITMAP != 0 {
        let nbytes = ((n_prev as usize) + 7) / 8;
        r.need(nbytes)?;
        bitmap.extend_from_slice(&buf[r.pos..r.pos + nbytes]);
        r.pos += nbytes;
    } else {
        let mut prev = 0u32;
        for _ in 0..n_change {
            let d = r.varint()? as u32;
            prev = prev.wrapping_add(d);
            change_ids.push(prev);
        }
    }

    let mut escapes = Vec::with_capacity(n_escape);
    for _ in 0..n_escape {
        escapes.push(r.svarint()? as i32);
    }

    r.align();

    let mut change = Vec::with_capacity(n_change);
    // Which objects changed: from the bitmap (index into the previous set) or from the id list.
    let mut changed_ids: Vec<u32> = Vec::new();
    if flags & FLAG_CHANGE_BITMAP != 0 {
        if prev_ids.len() != n_prev as usize {
            return Err(WireError::Gap);
        }
        for i in 0..n_prev as usize {
            if bitmap[i / 8] >> (i % 8) & 1 == 1 {
                changed_ids.push(prev_ids[i]);
            }
        }
        if changed_ids.len() != n_change {
            return Err(WireError::Gap);
        }
    }

    for e in enter.iter_mut() {
        for axis in 0..3 {
            e.pos[axis] = r.bits(POS_ABS_BITS as u32)? as u16;
        }
        if flags & FLAG_VELOCITY != 0 {
            for axis in 0..3 {
                let u = r.bits(VEL_ABS_BITS as u32)? as i32;
                e.vel[axis] = (u - VEL_BIAS) as i16;
            }
        }
    }

    let mut esc_idx = 0usize;
    for k in 0..n_change {
        let mask = r.bits(2)?;
        let has_pos = mask & 1 != 0;
        let has_vel = mask & 2 != 0;
        let mut dpos = [0i32; 3];
        let mut dvel = [0i32; 3];
        if has_pos {
            for axis in 0..3 {
                let w = pos_delta_bits[axis];
                let u = r.bits(w as u32)?;
                if u == (1u64 << w) - 1 {
                    if esc_idx >= escapes.len() {
                        return Err(WireError::EscapeUnderflow);
                    }
                    dpos[axis] = escapes[esc_idx];
                    esc_idx += 1;
                } else {
                    dpos[axis] = signed_from_biased(u, w);
                }
            }
        }
        if has_vel {
            for axis in 0..3 {
                let w = vel_delta_bits[axis];
                let u = r.bits(w as u32)?;
                if u == (1u64 << w) - 1 {
                    if esc_idx >= escapes.len() {
                        return Err(WireError::EscapeUnderflow);
                    }
                    dvel[axis] = escapes[esc_idx];
                    esc_idx += 1;
                } else {
                    dvel[axis] = signed_from_biased(u, w);
                }
            }
        }
        let id = if flags & FLAG_CHANGE_BITMAP != 0 {
            changed_ids[k]
        } else {
            change_ids[k]
        };
        change.push(ChangeRec { id, dpos, dvel, has_pos, has_vel });
    }

    Ok(Packet {
        flags,
        tick,
        since_version,
        n_region,
        n_prev,
        enter,
        leave,
        change,
        bitmap,
        pos_delta_bits,
        vel_delta_bits,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rnd(seed: &mut u64) -> u64 {
        *seed ^= *seed << 13;
        *seed ^= *seed >> 7;
        *seed ^= *seed << 17;
        *seed
    }

    #[test]
    fn varint_roundtrip() {
        let mut seed = 0x12345678u64;
        let mut buf: Vec<u8> = Vec::new();
        let mut w = BitWriter::new(&mut buf);
        let vals: Vec<i64> = (0..64)
            .map(|_| (rnd(&mut seed) % 100_000) as i64 - 50_000)
            .collect();
        for v in &vals {
            w.svarint(*v);
        }
        w.finish();
        let mut r = BitReader::new(&buf);
        for v in &vals {
            assert_eq!(r.svarint().unwrap(), *v);
        }
    }

    #[test]
    fn bits_roundtrip() {
        let mut buf: Vec<u8> = Vec::new();
        let mut w = BitWriter::new(&mut buf);
        w.bits(0b1011, 4);
        w.bits(0, 3);
        w.bits(0xABCD, 16);
        w.finish();
        let mut r = BitReader::new(&buf);
        assert_eq!(r.bits(4).unwrap(), 0b1011);
        assert_eq!(r.bits(3).unwrap(), 0);
        assert_eq!(r.bits(16).unwrap(), 0xABCD);
    }

    /// Random packets must survive encode/decode unchanged.
    #[test]
    fn packet_roundtrip_fuzz() {
        let mut seed = 0xDEADBEEFu64;
        for iter in 0..2000 {
            let mut pkt = Packet {
                flags: FLAG_VELOCITY | (if iter % 3 == 0 { FLAG_CHANGE_BITMAP } else { 0 }),
                tick: (rnd(&mut seed) % 100_000) as u32,
                since_version: (rnd(&mut seed) % 100_000) as u32,
                n_region: 0,
                n_prev: 0,
                ..Default::default()
            };
            let n_enter = (rnd(&mut seed) % 6) as usize;
            let mut id = 0u32;
            for _ in 0..n_enter {
                id += 1 + (rnd(&mut seed) % 100) as u32;
                pkt.enter.push(EnterRec {
                    id,
                    pos: [
                        (rnd(&mut seed) % 20001) as u16,
                        (rnd(&mut seed) % 20001) as u16,
                        (rnd(&mut seed) % 12001) as u16,
                    ],
                    vel: [
                        (rnd(&mut seed) % 8000) as i16 - 4000,
                        (rnd(&mut seed) % 8000) as i16 - 4000,
                        (rnd(&mut seed) % 8000) as i16 - 4000,
                    ],
                });
            }
            let n_change = (rnd(&mut seed) % 8) as usize;
            let mut id = 0u32;
            for _ in 0..n_change {
                id += 1 + (rnd(&mut seed) % 50) as u32;
                let has_pos = rnd(&mut seed) % 4 != 0;
                let has_vel = rnd(&mut seed) % 3 != 0;
                pkt.change.push(ChangeRec {
                    id,
                    dpos: [
                        (rnd(&mut seed) % 20001) as i32 - 10000,
                        (rnd(&mut seed) % 20001) as i32 - 10000,
                        (rnd(&mut seed) % 20001) as i32 - 10000,
                    ],
                    dvel: [
                        (rnd(&mut seed) % 20001) as i32 - 10000,
                        (rnd(&mut seed) % 20001) as i32 - 10000,
                        (rnd(&mut seed) % 20001) as i32 - 10000,
                    ],
                    has_pos,
                    has_vel,
                });
            }
            let n_leave = (rnd(&mut seed) % 4) as usize;
            let mut id = 0u32;
            for _ in 0..n_leave {
                id += 1 + (rnd(&mut seed) % 100) as u32;
                pkt.leave.push(id);
            }
            pkt.n_region = (pkt.enter.len() + pkt.change.len()) as u32;
            let mut prev_ids: Vec<u32> = Vec::new();
            let mut pid = 0u32;
            let n_prev = (rnd(&mut seed) % 200) as usize;
            for _ in 0..n_prev {
                pid += 1 + (rnd(&mut seed) % 20) as u32;
                prev_ids.push(pid);
            }
            if pkt.flags & FLAG_CHANGE_BITMAP != 0 {
                // the changed objects must be distinct members of the previous set
                while prev_ids.len() < pkt.change.len() {
                    pid += 1 + (rnd(&mut seed) % 20) as u32;
                    prev_ids.push(pid);
                }
                let nbytes = ((prev_ids.len() + 7) / 8) as usize;
                pkt.n_prev = prev_ids.len() as u32;
                pkt.bitmap = vec![0u8; nbytes];
                let mut used = std::collections::HashSet::new();
                for c in pkt.change.iter_mut() {
                    let mut idx = (rnd(&mut seed) as usize) % prev_ids.len();
                    while !used.insert(idx) {
                        idx = (idx + 1) % prev_ids.len();
                    }
                    c.id = prev_ids[idx];
                }
                pkt.change.sort_by_key(|c| c.id);
                for c in pkt.change.iter() {
                    let idx = prev_ids.binary_search(&c.id).unwrap();
                    pkt.bitmap[idx / 8] |= 1 << (idx % 8);
                }
            }

            let mut out = Vec::new();
            let mut scratch = EncodeScratch::default();
            encode(&mut pkt, &mut out, &mut scratch);
            let dec = decode(&out, &prev_ids).expect("decode");
            assert_eq!(dec.tick, pkt.tick);
            assert_eq!(dec.since_version, pkt.since_version);
            assert_eq!(dec.enter, pkt.enter, "iter {}", iter);
            assert_eq!(dec.leave, pkt.leave, "iter {}", iter);
            assert_eq!(dec.change.len(), pkt.change.len());
            assert_eq!(dec.pos_delta_bits, pkt.pos_delta_bits);
            assert_eq!(dec.vel_delta_bits, pkt.vel_delta_bits);
            if pkt.flags & FLAG_CHANGE_BITMAP != 0 {
                // ids are implied by the bitmap
                assert_eq!(dec.change.len(), pkt.change.len());
                for (d, e) in dec.change.iter().zip(pkt.change.iter()) {
                    assert_eq!(d.has_pos, e.has_pos, "iter {}", iter);
                    assert_eq!(d.has_vel, e.has_vel, "iter {}", iter);
                    // a field that is not present is not on the wire at all
                    if e.has_pos {
                        assert_eq!(d.dpos, e.dpos, "iter {}", iter);
                    } else {
                        assert_eq!(d.dpos, [0, 0, 0], "iter {}", iter);
                    }
                    if e.has_vel {
                        assert_eq!(d.dvel, e.dvel, "iter {}", iter);
                    } else {
                        assert_eq!(d.dvel, [0, 0, 0], "iter {}", iter);
                    }
                }
            } else {
                for (d, e) in dec.change.iter().zip(pkt.change.iter()) {
                    assert_eq!(d.id, e.id, "iter {}", iter);
                    assert_eq!(d.has_pos, e.has_pos, "iter {}", iter);
                    assert_eq!(d.has_vel, e.has_vel, "iter {}", iter);
                    if e.has_pos {
                        assert_eq!(d.dpos, e.dpos, "iter {}", iter);
                    } else {
                        assert_eq!(d.dpos, [0, 0, 0], "iter {}", iter);
                    }
                    if e.has_vel {
                        assert_eq!(d.dvel, e.dvel, "iter {}", iter);
                    } else {
                        assert_eq!(d.dvel, [0, 0, 0], "iter {}", iter);
                    }
                }
            }
        }
    }
}

