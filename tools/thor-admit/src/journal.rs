//! journal.rs — the decision log, chained.
//!
//! The daemon already writes an excellent flat JSON event log: one object
//! per line, `at`/`event`/`pid` plus the event's own fields. What that log
//! cannot prove is that it is the whole log — that nobody truncated it,
//! edited a line after the fact, or spliced two logs together. Every
//! post-mortem that reads it has to *assume* that, and the box's history
//! (a concurrent-task OOM that took the daemon's own narrative with it)
//! says the assumption is exactly what fails on the night you need it.
//!
//! The chain is the answer, and it is small: every line the daemon writes
//! carries `seq` (its number, unique across restarts) and `chain` (a
//! running FNV-1a hash folded over the line's own bytes and every line
//! before it). The fold covers the exact bytes of the line as serialized
//! *without* the `chain` field, so a verifier can recompute it from the
//! file alone — no key, no sidecar, nothing to back up. Editing a
//! historical line, deleting a middle line, or restarting the numbering
//! mid-file all break the chain at a named line; `thor-admit verify` says
//! which one.
//!
//! The arithmetic is the same mixer the ecology's kernel uses for its
//! necrology (`ecology_core::journal::fnv1a64`, in the ecology-thor repo)
//! — same offset basis, same prime, per-byte — so a chain walked here and
//! a chain walked there agree byte-for-byte on identical input. It is
//! inlined rather than imported: three lines of constants, and this crate
//! stays dependency-free the way it was.
//!
//! What the chain is **not**: cryptography. FNV-1a is a mixer, not a MAC;
//! an adversary who can rewrite the whole file can re-chain it. The threat
//! model is the honest one — truncated logs, after-the-fact edits, splice
//! mistakes, the wrong file copied into the bug report — not an attacker.

use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use serde_json::Value;

/// The FNV-1a 64-bit offset basis.
const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
/// The FNV-1a 64-bit prime.
const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

/// Fold one byte into the mix. The whole mixer, inlined so the crate keeps
/// its zero non-stdlib-dependency shape.
#[inline]
pub fn fnv1a64(mut mix: u64, bytes: &[u8]) -> u64 {
    for byte in bytes {
        mix ^= *byte as u64;
        mix = mix.wrapping_mul(FNV_PRIME);
    }
    mix
}

/// The running chain: the last seq written and the mix after it.
///
/// One `Chain` lives in the daemon next to the log file, locked the same
/// way; `seal` is the only thing that advances it.
#[derive(Debug)]
pub struct Chain {
    seq: u64,
    mix: u64,
}

impl Chain {
    /// A chain that starts fresh: seq 0 (the first seal writes 1), mix at
    /// the offset basis.
    pub fn fresh() -> Self {
        Chain {
            seq: 0,
            mix: FNV_OFFSET,
        }
    }

    /// Resume the chain from the last chained line of `path`, so a daemon
    /// restart continues the same chain — the seqs keep counting and the
    /// morning's `verify` still passes over the whole file, restarts and
    /// all. A file that does not exist or has no chained line yet starts
    /// fresh; that is the first-boot case, not an error.
    pub fn resume(path: &Path) -> Self {
        let mut chain = Chain::fresh();
        if let Ok(file) = File::open(path) {
            for line in BufReader::new(file).lines().map_while(Result::ok) {
                if let Ok(value) = serde_json::from_str::<Value>(&line) {
                    if let (Some(seq), Some(mix)) = (value["seq"].as_u64(), parse_mix(&value)) {
                        chain.seq = seq;
                        chain.mix = mix;
                    }
                }
            }
        }
        chain
    }

    /// The mix as it stands — the chain's head, what `verify` reports.
    pub fn mix_of(&self) -> u64 {
        self.mix
    }

    /// Number the next line and fold it in. `line` is the event as it will
    /// be serialized *without* `seq` and `chain`; the returned mix is what
    /// the written line's `chain` field must carry. Callers insert the two
    /// fields after sealing, and the verifier removes them before
    /// re-serializing — writer and reader fold over identical bytes.
    pub fn seal(&mut self, line: &Value) -> (u64, u64) {
        self.seq += 1;
        let mut mix = fnv1a64(self.mix, &self.seq.to_le_bytes());
        mix = fnv1a64(mix, serde_json::to_string(line).unwrap_or_default().as_bytes());
        self.mix = mix;
        (self.seq, mix)
    }
}

/// Read a line's claimed `chain` as a number (`"1a2b…"` hex).
fn parse_mix(value: &Value) -> Option<u64> {
    let text = value["chain"].as_str()?;
    u64::from_str_radix(text.trim_start_matches("0x"), 16).ok()
}

/// What `verify` says about a file whose chain held.
#[derive(Debug, PartialEq, Eq)]
pub struct Intact {
    /// Lines carrying a chain, in order.
    pub chained: u64,
    /// Lines before the first chained one — an older daemon, pre-chain,
    /// wrote them. They are reported, not judged: the chain speaks only
    /// for the lines it covers.
    pub unchained: u64,
    /// The mix after the last line — the chain's head. Two logs of the
    /// same events end on the same head, which is how a copy is checked
    /// against an original without re-reading every line.
    pub head: u64,
}

/// Where and why a chain broke.
#[derive(Debug, PartialEq, Eq)]
pub struct Break {
    /// The seq of the offending line (0 when the line carried none).
    pub seq: u64,
    pub reason: Reason,
}

/// The ways a chain breaks — each one a sentence an operator can act on.
#[derive(Debug, PartialEq, Eq)]
pub enum Reason {
    /// The recomputed mix differs from the claimed one: this line was
    /// edited after it was written.
    Edited,
    /// The seq jumped or went backwards: lines were removed, or a fresh
    /// chain was started mid-file (a truncated log the daemon appended to).
    Numbering,
    /// The line is not a chained event at all — malformed JSON, or a chain
    /// field that is not a number.
    Malformed,
}

/// Walk `path` and verify its chain. Every line must carry the seq after
/// the one before it and the mix that folds forward from it; a single
/// failure stops the walk at that line, because nothing after a break can
/// be trusted to be what the daemon wrote.
pub fn verify(path: &Path) -> Result<Intact, Break> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(_) => return Err(Break { seq: 0, reason: Reason::Malformed }),
    };
    let mut mix = FNV_OFFSET;
    let mut last_seq: Option<u64> = None;
    let mut chained = 0u64;
    let mut unchained = 0u64;
    for line in BufReader::new(file).lines().map_while(Result::ok) {
        let value = match serde_json::from_str::<Value>(&line) {
            Ok(value) => value,
            Err(_) => {
                return Err(Break {
                    seq: last_seq.unwrap_or(0),
                    reason: Reason::Malformed,
                })
            }
        };
        let (seq, claimed) = match (value["seq"].as_u64(), parse_mix(&value)) {
            (Some(seq), Some(claimed)) => (seq, claimed),
            // A line with no chain fields: only acceptable as a prefix
            // written by an older daemon. A gap in the middle means the
            // file was spliced; the chain cannot speak past it.
            _ if last_seq.is_none() => {
                unchained += 1;
                continue;
            }
            _ => {
                return Err(Break {
                    seq: last_seq.unwrap_or(0),
                    reason: Reason::Malformed,
                })
            }
        };
        if let Some(previous) = last_seq {
            if seq != previous + 1 {
                return Err(Break {
                    seq,
                    reason: Reason::Numbering,
                });
            }
        }
        // Recompute: the line's bytes as serialized without seq and chain.
        let mut bare = value.clone();
        if let Some(map) = bare.as_object_mut() {
            map.remove("seq");
            map.remove("chain");
        }
        let mut folded = fnv1a64(mix, &seq.to_le_bytes());
        folded = fnv1a64(folded, serde_json::to_string(&bare).unwrap_or_default().as_bytes());
        if folded != claimed {
            return Err(Break {
                seq,
                reason: Reason::Edited,
            });
        }
        mix = folded;
        last_seq = Some(seq);
        chained += 1;
    }
    Ok(Intact {
        chained,
        unchained,
        head: mix,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn dir() -> std::path::PathBuf {
        let name = std::thread::current()
            .name()
            .unwrap_or("test")
            .to_ascii_lowercase()
            .replace([' ', ':'], "-");
        let dir = std::env::temp_dir().join(format!("thor-admit-journal-{}-{name}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn write_lines(path: &Path, lines: &[String]) {
        use std::io::Write;
        let mut file = File::create(path).unwrap();
        for line in lines {
            writeln!(file, "{line}").unwrap();
        }
    }

    /// Seal a flat event the way the daemon does: build it, seal it, add
    /// the two fields.
    fn seal_line(chain: &mut Chain, event: &str, payload: Value) -> String {
        let mut line = json!({ "at": "2026-11-01T00:00:00Z", "event": event, "pid": 4242 });
        if let (Some(map), Some(extra)) = (line.as_object_mut(), payload.as_object()) {
            for (key, value) in extra {
                map.insert(key.clone(), value.clone());
            }
        }
        let (seq, mix) = chain.seal(&line);
        line["seq"] = json!(seq);
        line["chain"] = json!(format!("{mix:016x}"));
        serde_json::to_string(&line).unwrap()
    }

    #[test]
    fn the_chain_holds_and_an_edit_breaks_it_at_the_line() {
        let dir = dir();
        let path = dir.join("daemon.log");
        let mut chain = Chain::fresh();
        let lines: Vec<String> = (0..10)
            .map(|i| {
                seal_line(
                    &mut chain,
                    "lease.granted",
                    json!({ "lease": i + 1, "peak_bytes": 30_000_000_000i64 }),
                )
            })
            .collect();
        write_lines(&path, &lines);
        let intact = verify(&path).unwrap();
        assert_eq!(intact.chained, 10);
        assert_eq!(intact.unchained, 0);
        assert_eq!(intact.head, chain.mix_of());

        // An edit to a historical line breaks the chain at that seq.
        let tampered = lines[3].replace("30000000000", "1000000000");
        let mut edited = lines.clone();
        edited[3] = tampered;
        write_lines(&path, &edited);
        assert_eq!(
            verify(&path),
            Err(Break { seq: 4, reason: Reason::Edited })
        );

        // Deleting a middle line breaks the numbering (and the mix).
        let mut gapped: Vec<String> = lines.clone();
        gapped.remove(6);
        write_lines(&path, &gapped);
        assert_eq!(
            verify(&path),
            Err(Break { seq: 8, reason: Reason::Numbering })
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn the_chain_resumes_across_a_restart_and_the_whole_file_verifies() {
        let dir = dir();
        let path = dir.join("daemon.log");
        let mut lines: Vec<String> = Vec::new();
        {
            let mut chain = Chain::fresh();
            for i in 0..5 {
                lines.push(seal_line(&mut chain, "lease.granted", json!({ "lease": i + 1 })));
            }
        }
        write_lines(&path, &lines);
        // The daemon restarts: it resumes from the file's tail, and the
        // next line is seq 6, not seq 1.
        let mut chain = Chain::resume(&path);
        let next = seal_line(&mut chain, "lease.released", json!({ "lease": 5 }));
        assert!(next.contains("\"seq\":6"), "the resumed chain numbers on: {next}");
        lines.push(next);
        write_lines(&path, &lines);
        assert_eq!(verify(&path).unwrap().chained, 6);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn lines_from_an_older_daemon_are_a_reported_prefix_not_a_failure() {
        let dir = dir();
        let path = dir.join("daemon.log");
        // Two pre-chain lines, then the chain starts — the daemon upgraded
        // in place, with its state dir kept.
        let old = json!({ "at": "2026-10-30T00:00:00Z", "event": "daemon.started", "pid": 1 });
        let mut lines = vec![serde_json::to_string(&old).unwrap()];
        let mut chain = Chain::fresh();
        lines.push(seal_line(&mut chain, "lease.granted", json!({ "lease": 1 })));
        write_lines(&path, &lines);
        let intact = verify(&path).unwrap();
        assert_eq!((intact.unchained, intact.chained), (1, 1));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_fresh_chain_started_mid_file_is_caught_not_passed() {
        let dir = dir();
        let path = dir.join("daemon.log");
        // Five chained lines, then the file is truncated and the daemon
        // (its state wiped, its log copied back) appends a fresh chain.
        let mut lines: Vec<String> = Vec::new();
        let mut chain = Chain::fresh();
        for i in 0..5 {
            lines.push(seal_line(&mut chain, "lease.granted", json!({ "lease": i + 1 })));
        }
        let mut fresh = Chain::fresh();
        lines.push(seal_line(&mut fresh, "lease.granted", json!({ "lease": 99 })));
        write_lines(&path, &lines);
        assert_eq!(
            verify(&path),
            Err(Break { seq: 1, reason: Reason::Numbering })
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
