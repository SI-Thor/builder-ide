//! The protocol the CLI, the daemon and the Python shim speak.
//!
//! It is JSON, one object per line, over a Unix socket. Line-delimited JSON
//! is the smallest thing a Python shim can speak without a dependency, and it
//! is easy to read with `nc -U`.

use serde::de::{self, Deserializer};
use serde::{Deserialize, Serialize, Serializer};

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
        target: TargetSpec,
    },
    /// The client holds the lease's lock now.
    Held { lease: u64 },
    /// The lease is over.
    Release {
        lease: u64,
        #[serde(default)]
        peak_rss_bytes: Option<u64>,
    },
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
    pub age_s: f64,
    pub pid: i32,
    pub pgid: i32,
}

/// One waiter, as the status shows it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct QueueReport {
    pub position: usize,
    pub label: String,
    pub peak_bytes: u64,
    pub priority: i32,
    pub waiting_s: f64,
}

/// Everything the status shows.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct StatusReport {
    pub mem_total_bytes: u64,
    pub mem_available_bytes: u64,
    pub floor_bytes: u64,
    pub emergency_floor_bytes: u64,
    pub leases: Vec<LeaseReport>,
    pub queue: Vec<QueueReport>,
    pub gpu_source: String,
    pub gpu_visible: bool,
    pub gpu_box_used_bytes: Option<u64>,
    pub uptime_s: f64,
    /// How many memory samples the daemon has taken.
    pub samples: u64,
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
    /// The request cannot be served.
    Rejected { reason: String },
    /// Something went wrong.
    Error { message: String },
    /// The status.
    Status(Box<StatusReport>),
    /// Nothing to report.
    Ok,
}

impl Response {
    /// The event's name, for logs.
    pub fn event(&self) -> &'static str {
        match self {
            Response::Queued { .. } => "queued",
            Response::Granted { .. } => "granted",
            Response::Rejected { .. } => "rejected",
            Response::Error { .. } => "error",
            Response::Status(_) => "status",
            Response::Ok => "ok",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_request_round_trips() {
        let request = Request::Acquire {
            label: "trellis".to_string(),
            peak: PeakArg::Bytes(40_000_000_000),
            priority: 3,
            target: TargetSpec::Group { pgid: 1234 },
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
            target: TargetSpec::Process { pid: 7 },
        };
        let text = serde_json::to_string(&request).unwrap();
        assert!(text.contains("\"peak\":\"auto\""));
        let back: Request = serde_json::from_str(&text).unwrap();
        assert_eq!(back, request);
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
}
