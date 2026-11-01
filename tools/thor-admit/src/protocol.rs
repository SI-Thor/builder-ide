//! The protocol the CLI, the daemon and the Python shim speak.
//!
//! It is JSON, one object per line, over a Unix socket. Line-delimited JSON
//! is the smallest thing a Python shim can speak without a dependency, and it
//! is easy to read with `nc -U`.

use serde::de::{self, Deserializer};
use serde::{Deserialize, Serialize, Serializer};

use crate::ledger::Bucket;
use crate::tier::Tier;

/// What a client asks for: a size, or the daemon's own learned one.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PeakArg {
    /// `--peak auto`: the p95 of this label's history.
    Auto,
    /// An explicit number of bytes.
    Bytes(u64),
}

impl Serialize for PeakArg {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            PeakArg::Auto => serializer.serialize_str("auto"),
            PeakArg::Bytes(bytes) => serializer.serialize_u64(*bytes),
        }
    }
}

impl<'de> Deserialize<'de> for PeakArg {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<PeakArg, D::Error> {
        struct Visitor;
        impl de::Visitor<'_> for Visitor {
            type Value = PeakArg;

            fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                write!(f, "a byte count or the string \"auto\"")
            }

            fn visit_u64<E: de::Error>(self, value: u64) -> Result<PeakArg, E> {
                Ok(PeakArg::Bytes(value))
            }

            fn visit_i64<E: de::Error>(self, value: i64) -> Result<PeakArg, E> {
                if value < 0 {
                    return Err(de::Error::custom("a size cannot be negative"));
                }
                Ok(PeakArg::Bytes(value as u64))
            }

            fn visit_str<E: de::Error>(self, value: &str) -> Result<PeakArg, E> {
                if value.eq_ignore_ascii_case("auto") {
                    Ok(PeakArg::Auto)
                } else {
                    Err(de::Error::custom(format!("unknown peak {value:?}")))
                }
            }
        }
        deserializer.deserialize_any(Visitor)
    }
}

/// What the lease covers.
#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum TargetSpec {
    /// A whole process group — what `thor-admit run` leases.
    Group { pgid: i32 },
    /// One process — what the Python shim leases.
    Process { pid: i32 },
}

impl TargetSpec {
    /// The process group, if the target is a group.
    pub fn pgid(&self) -> Option<i32> {
        match self {
            TargetSpec::Group { pgid } => Some(*pgid),
            TargetSpec::Process { .. } => None,
        }
    }

    /// The process, if the target is a single process.
    pub fn pid(&self) -> Option<i32> {
        match self {
            TargetSpec::Group { .. } => None,
            TargetSpec::Process { pid } => Some(*pid),
        }
    }
}

/// A client asking for something.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum Request {
    /// Take a lease.
    Acquire {
        label: String,
        peak: PeakArg,
        #[serde(default)]
        priority: i32,
        /// Which tier of work this is. A lease that does not say is **live**.
        #[serde(default)]
        tier: Tier,
        target: TargetSpec,
        /// The coalescing key, set only by `thor-admit serve`: identical
        /// serve requests waiting side by side become one waiter (round 11).
        /// An opaque string — the daemon compares it for equality and
        /// understands nothing else about it; the serve client builds it
        /// from the model file and the command's flags, the same key the
        /// registry uses. `None` (every other client) never coalesces.
        #[serde(default)]
        coalesce: Option<String>,
    },
    /// The client holds the lease's lock now.
    Held { lease: u64 },
    /// The client is still there, still working, still holding the lock.
    ///
    /// The lock alone cannot say this: a client can hang — deadlocked,
    /// stopped, wedged — and a hung client's lock never drops, so its
    /// reservation would be charged forever. The heartbeat is the client
    /// saying "alive" on a schedule; the daemon decides what a silent client
    /// means (Hy4's fourth failure mode).
    Heartbeat { lease: u64 },
    /// The lease is over.
    Release {
        lease: u64,
        #[serde(default)]
        peak_rss_bytes: Option<u64>,
        /// How the command finished: 0 is a clean exit, `128 + signal` a
        /// kill. A lease whose run did not finish cleanly teaches the peak
        /// history nothing (see `PeakRecord::teaches`).
        #[serde(default)]
        exit_code: Option<i32>,
    },
    /// Change a running lease's reservation: the work changed phase.
    ///
    /// A lease that reserved far above its use may shrink (the freed bytes
    /// return to the headroom at once), and a lease that knows it needs
    /// more may grow — but only if the box has the room, so a grow that
    /// does not fit is refused and the lease keeps the reservation it has
    /// (`thor-admit phase`, round 11).
    Phase {
        lease: u64,
        peak: PeakArg,
    },
    /// Register a job in the presence queue.
    PresenceAdd {
        label: String,
        tier: Tier,
        peak: PeakArg,
        #[serde(default)]
        resumable: bool,
        command: Vec<String>,
        /// Is the job wanted? A disabled job stays registered and does not
        /// run — the shape an example or a held-over job takes.
        #[serde(default = "default_true")]
        enabled: bool,
    },
    /// Take a job out of the presence queue.
    PresenceRemove { id: u64 },
    /// What is in the presence queue?
    PresenceList,
    /// Re-read what the daemon reads from disk: the peak history and the
    /// presence queue.
    ///
    /// The daemon keeps both in memory, so an edit made by hand (an operator
    /// cleaning no-op records out of the history, a night runner editing the
    /// queue) is invisible to a running daemon until it reloads. `SIGHUP`
    /// does the same thing.
    Reload,
    /// The time ledger: the hours, and the hour being kept now.
    Ledger,
    /// What is going on?
    Status,
    /// Is the daemon alive?
    Ping,
}

/// One lease, as the status shows it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct LeaseReport {
    pub lease: u64,
    pub label: String,
    /// What the lease promised.
    pub peak_bytes: u64,
    /// What it is using right now.
    pub current_rss_bytes: u64,
    /// What it has used at most.
    pub peak_rss_bytes: u64,
    /// What it held on the GPU at most.
    pub peak_gpu_bytes: u64,
    pub priority: i32,
    /// Which tier of work this is.
    pub tier: Tier,
    pub age_s: f64,
    pub pid: i32,
    pub pgid: i32,
    /// The lease is holding far more than it uses: at least four times both
    /// its label's learned peak and its own measured peak, with 8 GiB of the
    /// promise still owed. The daemon names such a lease in the log
    /// (`lease.overreserved`); `thor-admit phase` is the answer, and this
    /// flag is how the holder learns it without reading the log.
    ///
    /// The default keeps a **new client readable against an old daemon**:
    /// the fields are the round-11 additions, and a client that asks an
    /// older daemon for its status must still read the answer.
    #[serde(default)]
    pub over_reserved: bool,
    /// The peak the daemon would suggest for an over-reserved lease: the
    /// larger of the label's learned p95 and the lease's measured peak.
    #[serde(default)]
    pub suggested_peak_bytes: u64,
}

/// One waiter, as the status shows it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct QueueReport {
    pub position: usize,
    pub label: String,
    pub peak_bytes: u64,
    pub priority: i32,
    pub waiting_s: f64,
    /// How many identical (coalesced) serve requests are waiting behind
    /// this one waiter. Zero for everything but a coalescing serve waiter;
    /// the queue's depth counts waiters, not askers, so two seats asking
    /// for the same server are one waiter with `coalesced: 1` (round 11).
    #[serde(default)]
    pub coalesced: usize,
}

/// Everything the status shows.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct StatusReport {
    pub mem_total_bytes: u64,
    pub mem_available_bytes: u64,
    pub floor_bytes: u64,
    pub emergency_floor_bytes: u64,
    /// The least the GPU's own allocation pool must keep free.
    pub gpu_floor_bytes: u64,
    pub leases: Vec<LeaseReport>,
    pub queue: Vec<QueueReport>,
    pub gpu_source: String,
    pub gpu_visible: bool,
    pub gpu_box_used_bytes: Option<u64>,
    /// The GPU's own allocation pool as `tegrastats`' `lfb` sees it, when it
    /// is visible. This is the number the `--gpu-floor` rule is applied to.
    pub gpu_largest_free_block_bytes: Option<u64>,
    pub uptime_s: f64,
    /// How many memory samples the daemon has taken.
    pub samples: u64,
    /// The presence queue: the registered work and what it is doing.
    pub presence: Vec<PresenceReport>,
}

/// One presence job, as the status shows it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct PresenceReport {
    pub id: u64,
    pub label: String,
    pub tier: Tier,
    pub peak_bytes: u64,
    pub resumable: bool,
    /// Is the job wanted? A disabled job stays registered and does not run.
    #[serde(default = "default_true")]
    pub enabled: bool,
    /// What the job is doing: pending, running, preempted, done, failed.
    pub state: String,
    /// The command, as one string.
    pub command: String,
    /// The process group, when it is running.
    pub pgid: i32,
    /// How long it has been running, in seconds.
    pub age_s: f64,
    /// What it is using right now, in bytes.
    pub current_rss_bytes: u64,
    /// How many times it has been started.
    pub attempts: u32,
    /// How many times live work has pre-empted it.
    pub preemptions: u32,
    /// The exit code of the last run.
    pub last_exit: Option<i32>,
}

/// The daemon's answer.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(tag = "event", rename_all = "snake_case")]
pub enum Response {
    /// The request is in the queue, waiting for room.
    Queued {
        position: usize,
        waiting: usize,
        available_bytes: u64,
    },
    /// The lease is granted.
    Granted {
        lease: u64,
        label: String,
        /// The peak the daemon will hold the lease to.
        peak_bytes: u64,
        /// The file the client must lock.
        lock_path: String,
        floor_bytes: u64,
        available_bytes: u64,
    },
    /// The request was coalesced into a lease that is being granted to
    /// another client: the same server, starting under lease `lease`.
    ///
    /// The asker should run nothing and wait for the server it asked for
    /// to answer (the serve client polls the registry, which the starting
    /// server's client records the moment its port answers). It arrives
    /// only to a request that sent a `coalesce` key.
    Coalesced { lease: u64, label: String },
    /// The request cannot be served.
    Rejected { reason: String },
    /// Something went wrong.
    Error { message: String },
    /// The status.
    Status(Box<StatusReport>),
    /// The presence queue.
    Presence {
        jobs: Vec<PresenceReport>,
    },
    /// The time ledger: the closed hours, and the hour being kept now.
    Ledger {
        buckets: Vec<Bucket>,
        /// The hour being kept right now.
        current: Box<Bucket>,
    },
    /// A presence job was registered.
    PresenceAdded {
        id: u64,
        label: String,
        tier: Tier,
    },
    /// The daemon re-read its history and its presence queue.
    Reloaded {
        /// How many peak records it is holding now.
        peaks: usize,
        /// How many presence jobs are registered now.
        presence: usize,
    },
    /// Nothing to report.
    Ok,
}

/// The default a `PresenceAdd` without `enabled` gets: wanted.
fn default_true() -> bool {
    true
}

impl Response {
    /// The event's name, for logs.
    pub fn event(&self) -> &'static str {
        match self {
            Response::Queued { .. } => "queued",
            Response::Granted { .. } => "granted",
            Response::Coalesced { .. } => "coalesced",
            Response::Rejected { .. } => "rejected",
            Response::Error { .. } => "error",
            Response::Status(_) => "status",
            Response::Presence { .. } => "presence",
            Response::Ledger { .. } => "ledger",
            Response::PresenceAdded { .. } => "presence_added",
            Response::Reloaded { .. } => "reloaded",
            Response::Ok => "ok",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_lease_report_from_an_older_daemon_still_reads() {
        // The shape a daemon that predates the phase op wrote: no
        // `over_reserved`, no `suggested_peak_bytes`. A new client asking an
        // older daemon for its status must still read the answer — the
        // swap window is exactly when that happens.
        let text = r#"{"lease":6,"label":"trellis","peak_bytes":1024,
                       "current_rss_bytes":512,"peak_rss_bytes":512,"peak_gpu_bytes":0,
                       "priority":0,"tier":"live","age_s":3.0,"pid":42,"pgid":42}"#;
        let report: LeaseReport = serde_json::from_str(text).unwrap();
        assert!(!report.over_reserved);
        assert_eq!(report.suggested_peak_bytes, 0);
    }

    #[test]
    fn a_request_round_trips() {
        let request = Request::Acquire {
            label: "trellis".to_string(),
            peak: PeakArg::Bytes(40_000_000_000),
            priority: 3,
            tier: Tier::Live,
            target: TargetSpec::Group { pgid: 1234 },
            coalesce: None,
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"op\":\"acquire\""));
        assert!(text.contains("\"peak\":40000000000"));
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);
    }

    #[test]
    fn auto_survives_the_round_trip() {
        let request = Request::Acquire {
            label: "trellis".to_string(),
            peak: PeakArg::Auto,
            priority: 0,
            tier: Tier::Study,
            target: TargetSpec::Process { pid: 7 },
            coalesce: None,
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"peak\":\"auto\""));
        assert!(text.contains("\"tier\":\"study\""));
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);
    }

    #[test]
    fn a_serve_request_carries_its_coalescing_key() {
        let request = Request::Acquire {
            label: "serve.glide".to_string(),
            peak: PeakArg::Bytes(62_277_025_792),
            priority: 0,
            tier: Tier::Live,
            target: TargetSpec::Group { pgid: 9 },
            coalesce: Some("file:/models/glide.gguf:abc123|--host 127.0.0.1".to_string()),
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"coalesce\":\"file:"), "{text}");
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);
    }

    #[test]
    fn a_coalesced_answer_round_trips() {
        let response = Response::Coalesced {
            lease: 14,
            label: "serve.glide".to_string(),
        };
        let text = serde_json::to_string(&response).unwrap();
        assert!(text.contains("\"event\":\"coalesced\""));
        let back: Response = serde_json::from_str(&text).unwrap();
        assert_eq!(back, response);
    }

    #[test]
    fn a_phase_request_round_trips() {
        let request = Request::Phase {
            lease: 11,
            peak: PeakArg::Bytes(5_000_000_000),
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"op\":\"phase\""));
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);
    }

    #[test]
    fn a_queue_report_without_the_coalesced_count_still_reads() {
        // The shape an older reader of the status wrote: no `coalesced`
        // field. It reads as zero.
        let text = r#"{"position":1,"label":"serve.glide","peak_bytes":1,
                       "priority":0,"waiting_s":12.0}"#;
        let report: QueueReport = serde_json::from_str(text).unwrap();
        assert_eq!(report.coalesced, 0);
    }

    #[test]
    fn a_request_from_the_python_shim_is_readable() {
        // The shape the shim writes by hand.
        let text = r#"{"op":"acquire","label":"seat","peak":"auto","priority":0,"target":{"process":{"pid":42}}}"#;
        let request: Request = serde_json::from_str(text).unwrap();
        match request {
            Request::Acquire { peak, target, .. } => {
                assert_eq!(peak, PeakArg::Auto);
                assert_eq!(target.pid(), Some(42));
                assert_eq!(target.pgid(), None);
            }
            other => panic!("wrong request: {other:?}"),
        }
    }

    #[test]
    fn a_response_round_trips() {
        let response = Response::Granted {
            lease: 7,
            label: "trellis".to_string(),
            peak_bytes: 1024,
            lock_path: "/tmp/x.lock".to_string(),
            floor_bytes: 2048,
            available_bytes: 4096,
        };
        let text = serde_json::to_string(&response).unwrap();
        assert!(text.contains("\"event\":\"granted\""));
        let back: Response = serde_json::from_str(&text).unwrap();
        assert_eq!(back, response);
    }

    #[test]
    fn the_presence_requests_round_trip() {
        let request = Request::PresenceAdd {
            label: "sweep".to_string(),
            tier: Tier::Study,
            peak: PeakArg::Bytes(1024),
            resumable: true,
            command: vec!["python3".to_string(), "sweep.py".to_string()],
            enabled: false,
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"op\":\"presence_add\""));
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);

        let list = Request::PresenceList;
        let text = serde_json::to_string(&list).unwrap();
        assert_eq!(text, "{\"op\":\"presence_list\"}");
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, list);
    }

    #[test]
    fn a_release_carries_how_the_run_finished() {
        let request = Request::Release {
            lease: 7,
            peak_rss_bytes: Some(1234),
            exit_code: Some(0),
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"exit_code\":0"), "{text}");
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);

        // And the shape an older client writes — no exit status — is still
        // readable, as an unknown finish.
        let old = r#"{"op":"release","lease":7}"#;
        let back: Request = serde_json::from_str(old).unwrap();
        assert_eq!(
            back,
            Request::Release {
                lease: 7,
                peak_rss_bytes: None,
                exit_code: None
            }
        );
    }

    #[test]
    fn a_presence_add_without_enabled_is_wanted() {
        // The shape an older client writes.
        let text = r#"{"op":"presence_add","label":"sweep","tier":"study","peak":1024,
                       "resumable":true,"command":["true"]}"#;
        let request: Request = serde_json::from_str(text).unwrap();
        match request {
            Request::PresenceAdd { enabled, .. } => assert!(enabled),
            other => panic!("wrong request: {other:?}"),
        }
    }

    #[test]
    fn the_reload_request_round_trips() {
        let text = serde_json::to_string(&Request::Reload).unwrap();
        assert_eq!(text, "{\"op\":\"reload\"}");
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, Request::Reload);
    }

    #[test]
    fn a_presence_spec_survives_the_round_trip() {
        let spec = crate::presence::PresenceSpec::new(
            3,
            "sweep",
            Tier::Practice,
            1024,
            true,
            vec!["sleep".to_string(), "1".to_string()],
        );
        let text = serde_json::to_string(&spec).unwrap();
        let back: crate::presence::PresenceSpec = serde_json::from_str(&text).unwrap();
        assert_eq!(back, spec);
    }
}
