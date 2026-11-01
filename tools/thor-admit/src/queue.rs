//! The waiting queue: first in, first out, with priorities in front.
//!
//! A higher priority waiter goes before the ones already waiting; waiters of
//! the same priority keep the order they arrived in.

use crate::tier::Tier;

/// One waiting request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Waiter {
    /// The lease id the daemon will use when this waiter is admitted.
    pub id: u64,
    pub label: String,
    pub peak_bytes: u64,
    /// The device memory this label has historically held, which the GPU's
    /// own pool must have room for on top of the GPU floor. Zero when the
    /// history has never seen the label touch the GPU.
    pub peak_gpu: u64,
    /// Higher runs first. The default is 0.
    pub priority: i32,
    /// Which tier of work this is. Only a live waiter may pre-empt the
    /// presence queue.
    pub tier: Tier,
    /// The arrival order, assigned by the queue.
    pub seq: u64,
}

/// The queue the admission rule drains.
#[derive(Debug, Default)]
pub struct Queue {
    items: Vec<Waiter>,
    next_seq: u64,
}

impl Queue {
    pub fn new() -> Self {
        Queue::default()
    }

    /// Put a waiter in the queue. The arrival order is assigned here.
    pub fn push(&mut self, mut waiter: Waiter) {
        waiter.seq = self.next_seq;
        self.next_seq += 1;
        // The first waiter with a *lower* priority is where this one goes:
        // everything ahead of it is of equal or higher priority.
        let position = self
            .items
            .iter()
            .position(|other| other.priority < waiter.priority)
            .unwrap_or(self.items.len());
        self.items.insert(position, waiter);
    }

    /// The waiter the rule looks at next.
    pub fn peek(&self) -> Option<&Waiter> {
        self.items.first()
    }

    /// Take the waiter the rule looks at next.
    pub fn pop(&mut self) -> Option<Waiter> {
        if self.items.is_empty() {
            None
        } else {
            Some(self.items.remove(0))
        }
    }

    /// Drop a waiter that gave up (its client went away).
    pub fn remove(&mut self, id: u64) -> Option<Waiter> {
        let index = self.items.iter().position(|w| w.id == id)?;
        Some(self.items.remove(index))
    }

    pub fn len(&self) -> usize {
        self.items.len()
    }

    pub fn is_empty(&self) -> bool {
        self.items.is_empty()
    }

    pub fn iter(&self) -> std::slice::Iter<'_, Waiter> {
        self.items.iter()
    }

    /// Where a waiter sits in the queue, counted from 1.
    pub fn position(&self, id: u64) -> Option<usize> {
        self.items.iter().position(|w| w.id == id).map(|i| i + 1)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn waiter(id: u64, priority: i32) -> Waiter {
        Waiter {
            id,
            label: format!("w{id}"),
            peak_bytes: 1024,
            peak_gpu: 0,
            priority,
            tier: Tier::Live,
            seq: 0,
        }
    }

    #[test]
    fn same_priority_keeps_arrival_order() {
        let mut queue = Queue::new();
        queue.push(waiter(1, 0));
        queue.push(waiter(2, 0));
        queue.push(waiter(3, 0));
        let order: Vec<u64> = queue.iter().map(|w| w.id).collect();
        assert_eq!(order, vec![1, 2, 3]);
    }

    #[test]
    fn a_higher_priority_waiter_goes_first() {
        let mut queue = Queue::new();
        queue.push(waiter(1, 0));
        queue.push(waiter(2, 0));
        queue.push(waiter(3, 5));
        let order: Vec<u64> = queue.iter().map(|w| w.id).collect();
        assert_eq!(order, vec![3, 1, 2]);
    }

    #[test]
    fn a_lower_priority_waiter_goes_last() {
        let mut queue = Queue::new();
        queue.push(waiter(1, 0));
        queue.push(waiter(2, 5));
        queue.push(waiter(3, -1));
        let order: Vec<u64> = queue.iter().map(|w| w.id).collect();
        assert_eq!(order, vec![2, 1, 3]);
    }

    #[test]
    fn priority_wins_over_arrival_but_not_over_itself() {
        let mut queue = Queue::new();
        queue.push(waiter(1, 0));
        queue.push(waiter(2, 5));
        queue.push(waiter(3, 5));
        let order: Vec<u64> = queue.iter().map(|w| w.id).collect();
        assert_eq!(order, vec![2, 3, 1]);
    }

    #[test]
    fn pop_takes_the_front_and_remove_takes_by_id() {
        let mut queue = Queue::new();
        queue.push(waiter(1, 0));
        queue.push(waiter(2, 3));
        queue.push(waiter(3, 0));
        assert_eq!(queue.pop().unwrap().id, 2);
        assert_eq!(queue.remove(3).unwrap().id, 3);
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.peek().unwrap().id, 1);
    }

    #[test]
    fn a_removed_waiter_is_gone() {
        let mut queue = Queue::new();
        queue.push(waiter(7, 0));
        assert!(queue.remove(7).is_some());
        assert!(queue.is_empty());
        assert_eq!(queue.position(7), None);
    }
}
