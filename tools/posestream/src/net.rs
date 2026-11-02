//! The simulated network: one lossy, delayed link per subscriber.
//!
//! A number that comes out of a simulation is only worth what the simulation's assumptions
//! are worth, so they are written down here and repeated in the README:
//!
//! * the one-way delay is drawn per packet, uniformly from `[delay_min, delay_max]`
//!   milliseconds, plus a zero-mean uniform jitter of `+/- jitter` milliseconds;
//! * a packet is lost with probability `loss`, independently of everything else;
//! * the delay stays below one tick (16.667 ms), so the packets of one subscriber never
//!   reorder: the link is FIFO. The harness asserts this rather than assuming it;
//! * the resync request travels the other way over the same link, with the same delay.
//!
//! The clock is in microticks (1e6 microticks = 1 tick = 16.667 ms), because the receiver
//! has to know *when* a packet arrived to the microsecond: that is what "back-dating" means.

use crate::world::{Rng, MICROTICKS_PER_MS};
use std::collections::VecDeque;

/// What the link does.
#[derive(Clone, Copy, Debug)]
pub struct NetConfig {
    /// False: the loopback (no delay, no loss), the run the winner was measured with.
    pub enabled: bool,
    pub delay_min_ms: f64,
    pub delay_max_ms: f64,
    pub jitter_ms: f64,
    /// The probability that a packet is lost.
    pub loss: f64,
}

impl Default for NetConfig {
    fn default() -> Self {
        NetConfig {
            enabled: false,
            delay_min_ms: 0.0,
            delay_max_ms: 0.0,
            jitter_ms: 0.0,
            loss: 0.0,
        }
    }
}

impl NetConfig {
    /// The network the brief asks for: 2-12 ms with jitter.
    pub fn standard(loss: f64) -> NetConfig {
        NetConfig {
            enabled: true,
            delay_min_ms: 2.0,
            delay_max_ms: 12.0,
            jitter_ms: 1.5,
            loss,
        }
    }

    /// The largest one-way delay this configuration can produce, in microticks.
    pub fn max_delay_us(&self) -> u64 {
        let ms = (self.delay_max_ms + self.jitter_ms).max(0.0);
        (ms * MICROTICKS_PER_MS) as u64
    }

    /// The smallest one-way delay, in microticks.
    pub fn min_delay_us(&self) -> u64 {
        let ms = (self.delay_min_ms - self.jitter_ms).max(0.0);
        (ms * MICROTICKS_PER_MS) as u64
    }

    pub fn describe(&self) -> String {
        if !self.enabled {
            return "loopback: no delay, no loss".to_string();
        }
        format!(
            "one-way delay uniform in [{:.1}, {:.1}] ms +/- {:.1} ms jitter, loss {:.2}% per packet",
            self.delay_min_ms,
            self.delay_max_ms,
            self.jitter_ms,
            self.loss * 100.0
        )
    }
}

/// A packet in flight, with the emitter's state at the moment it was built.
///
/// The snapshot is what the referee checks the receiver against: the quantised truth at the
/// packet's tick, and the emitter's mirror of the subscriber's state (the truth at each
/// object's last correction). Keeping the truth with the packet is what lets the referee
/// check a packet that arrives after the world has moved on.
pub struct InFlight {
    pub bytes: Vec<u8>,
    /// The virtual time the packet arrives at the receiver.
    pub arrive_us: u64,
    /// The emitter tick the packet was built at.
    pub tick: u32,
    /// How long the emitter waited for this subscriber before it could serve it: the time
    /// from the world commit to this packet's emission, in milliseconds.
    pub emit_wait_ms: f64,
    /// When the emitter started building this packet: the late-join figure is measured from
    /// here to the end of the receiver's verification.
    pub build_start: std::time::Instant,
    /// The objects in the subscriber's region at `tick`, ascending.
    pub ids: Vec<u32>,
    /// The quantised truth of each object at `tick`.
    pub truth: Vec<[i32; 3]>,
    /// The emitter's mirror of each object's state (the truth at its last correction).
    pub mirror_pos: Vec<[i32; 3]>,
    pub mirror_vel: Vec<[i32; 3]>,
    /// And the time that mirror state refers to.
    pub mirror_anchor: Vec<u64>,
}

/// One subscriber's link.
pub struct Link {
    cfg: NetConfig,
    rng: Rng,
    queue: VecDeque<InFlight>,
    /// Resync requests on their way back to the emitter, by arrival time.
    requests: VecDeque<u64>,
    pub sent: u64,
    pub lost: u64,
    pub delivered: u64,
    pub bytes_sent: u64,
    pub bytes_delivered: u64,
    pub reorderings: u64,
}

impl Link {
    pub fn new(cfg: NetConfig, seed: u64) -> Link {
        Link {
            cfg,
            rng: Rng::new(seed ^ 0x5DEE_CE66_D000_0002),
            queue: VecDeque::new(),
            requests: VecDeque::new(),
            sent: 0,
            lost: 0,
            delivered: 0,
            bytes_sent: 0,
            bytes_delivered: 0,
            reorderings: 0,
        }
    }

    /// Draw the one-way delay for the next packet, in microticks.
    pub fn draw_delay_us(&mut self) -> u64 {
        if !self.cfg.enabled {
            return 0;
        }
        let lo = self.cfg.delay_min_ms - self.cfg.jitter_ms;
        let hi = self.cfg.delay_max_ms + self.cfg.jitter_ms;
        let ms = lo + (hi - lo) * self.rng.f64();
        (ms.max(0.0) * MICROTICKS_PER_MS) as u64
    }

    /// Is this packet lost on the way?
    pub fn is_lost(&mut self) -> bool {
        if !self.cfg.enabled || self.cfg.loss <= 0.0 {
            return false;
        }
        self.rng.f64() < self.cfg.loss
    }

    /// Put a packet on the wire. `arrive_us` is the absolute arrival time.
    pub fn send(&mut self, pkt: InFlight) {
        self.sent += 1;
        self.bytes_sent += pkt.bytes.len() as u64;
        // The link is FIFO: the packets of one subscriber must not overtake each other.
        if let Some(back) = self.queue.back() {
            if pkt.arrive_us < back.arrive_us {
                self.reorderings += 1;
            }
        }
        self.queue.push_back(pkt);
    }

    /// The packets that have arrived by `now_us`, in order.
    pub fn drain(&mut self, now_us: u64, out: &mut Vec<InFlight>) {
        while let Some(front) = self.queue.front() {
            if front.arrive_us > now_us {
                break;
            }
            let pkt = self.queue.pop_front().unwrap();
            self.delivered += 1;
            self.bytes_delivered += pkt.bytes.len() as u64;
            out.push(pkt);
        }
    }

    /// The number of packets still in flight.
    pub fn inflight(&self) -> usize {
        self.queue.len()
    }

    /// A resync request leaves the receiver now and arrives at the emitter after the delay.
    pub fn request(&mut self, now_us: u64) {
        let d = self.draw_delay_us();
        self.requests.push_back(now_us + d);
    }

    /// Has a resync request reached the emitter by `now_us`?
    pub fn request_arrived(&mut self, now_us: u64) -> bool {
        let mut arrived = false;
        while let Some(front) = self.requests.front() {
            if *front > now_us {
                break;
            }
            self.requests.pop_front();
            arrived = true;
        }
        arrived
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_link_loses_only_what_it_is_told_to() {
        let cfg = NetConfig::standard(0.0);
        let mut link = Link::new(cfg, 1);
        for _ in 0..1000 {
            assert!(!link.is_lost());
        }
        let cfg = NetConfig::standard(1.0);
        let mut link = Link::new(cfg, 1);
        for _ in 0..1000 {
            assert!(link.is_lost());
        }
    }

    #[test]
    fn the_delay_stays_inside_the_configured_window() {
        let cfg = NetConfig::standard(0.005);
        let mut link = Link::new(cfg, 7);
        for _ in 0..10_000 {
            let d = link.draw_delay_us();
            assert!(d >= cfg.min_delay_us(), "delay {} us", d);
            assert!(d <= cfg.max_delay_us(), "delay {} us", d);
        }
    }

    /// The packets of one subscriber must not overtake each other, or the receiver's
    /// version check would fire on a packet that did arrive.
    #[test]
    fn packets_do_not_reorder() {
        let cfg = NetConfig::standard(0.02);
        let mut link = Link::new(cfg, 11);
        let mut last = 0u64;
        for tick in 1..3600u64 {
            let arrive = tick * crate::world::TICK_US + link.draw_delay_us();
            assert!(arrive >= last, "reordered at tick {}", tick);
            last = arrive;
        }
    }
}
