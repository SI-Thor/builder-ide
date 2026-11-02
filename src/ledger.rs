//! The append-only, hash-chained ledger.
//!
//! One JSON object per line in `ledger.jsonl`. Every row carries the hash of
//! the row before it, so the file is tamper-evident: change one byte of any
//! row and the chain from that row on no longer verifies.
//!
//! The hash covers a fixed field order (seq, ts, kind, prev, body), not the
//! JSON text of the row, so the row can be re-serialised for reading without
//! changing its hash.

use crate::json::Json;
use crate::sha256::sha256_hex;
use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

/// The hash the first row chains from.
pub const GENESIS: &str = "0000000000000000000000000000000000000000000000000000000000000000";

/// The domain separator, so a hash from this ledger cannot be confused with
/// a hash of the same bytes in some other context.
pub const DOMAIN: &str = "gc-ledger-v1";

#[derive(Clone, Debug)]
pub struct Row {
    pub seq: u64,
    pub ts: String,
    pub kind: String,
    pub body: Json,
    pub prev: String,
    pub hash: String,
}

impl Row {
    /// The exact bytes the row hash is taken over.
    pub fn hash_input(seq: u64, ts: &str, kind: &str, prev: &str, body: &Json) -> String {
        format!(
            "{}\n{}\n{}\n{}\n{}",
            DOMAIN,
            seq,
            ts,
            kind,
            format!("{}\n{}", prev, body.to_text())
        )
    }

    pub fn compute_hash(&self) -> String {
        sha256_hex(Row::hash_input(self.seq, &self.ts, &self.kind, &self.prev, &self.body).as_bytes())
    }

    pub fn to_json(&self) -> Json {
        let mut o = Json::obj();
        o.set("seq", Json::n(self.seq as f64));
        o.set("ts", Json::s(self.ts.clone()));
        o.set("kind", Json::s(self.kind.clone()));
        o.set("body", self.body.clone());
        o.set("prev", Json::s(self.prev.clone()));
        o.set("hash", Json::s(self.hash.clone()));
        o
    }

    pub fn from_json(v: &Json) -> Result<Row, String> {
        let seq = v.u64_at("seq").ok_or("row has no seq")?;
        let ts = v.str_at("ts").ok_or("row has no ts")?.to_string();
        let kind = v.str_at("kind").ok_or("row has no kind")?.to_string();
        let body = v.get("body").cloned().ok_or("row has no body")?;
        let prev = v.str_at("prev").ok_or("row has no prev")?.to_string();
        let hash = v.str_at("hash").ok_or("row has no hash")?.to_string();
        Ok(Row {
            seq,
            ts,
            kind,
            body,
            prev,
            hash,
        })
    }
}

/// Default ledger path, relative to the working directory.
pub fn default_path() -> PathBuf {
    PathBuf::from("ledger.jsonl")
}

/// Read and verify the whole ledger. Verification checks, for every row:
/// the row's `prev` equals the previous row's hash, and the row's `hash`
/// equals the hash recomputed from its own fields.
pub fn read(path: &Path) -> Result<Vec<Row>, String> {
    let file = match File::open(path) {
        Ok(f) => f,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(e) => return Err(format!("cannot open ledger {}: {}", path.display(), e)),
    };
    let reader = BufReader::new(file);
    let mut rows: Vec<Row> = Vec::new();
    let mut prev_hash = GENESIS.to_string();
    let mut expected_seq = 0u64;

    for (i, line) in reader.lines().enumerate() {
        let line = line.map_err(|e| format!("cannot read ledger line {}: {}", i + 1, e))?;
        if line.trim().is_empty() {
            continue;
        }
        let value = Json::parse(&line).map_err(|e| format!("ledger line {}: {}", i + 1, e))?;
        let row = Row::from_json(&value).map_err(|e| format!("ledger line {}: {}", i + 1, e))?;
        if row.seq != expected_seq {
            return Err(format!(
                "ledger line {}: expected seq {}, found {}",
                i + 1,
                expected_seq,
                row.seq
            ));
        }
        if row.prev != prev_hash {
            return Err(format!(
                "ledger line {} (seq {}): prev hash does not match the previous row",
                i + 1,
                row.seq
            ));
        }
        let recomputed = row.compute_hash();
        if recomputed != row.hash {
            return Err(format!(
                "ledger line {} (seq {}): hash does not match its contents (row was changed)",
                i + 1,
                row.seq
            ));
        }
        prev_hash = row.hash.clone();
        expected_seq += 1;
        rows.push(row);
    }
    Ok(rows)
}

/// Verify only; returns the number of rows checked.
pub fn verify(path: &Path) -> Result<usize, String> {
    Ok(read(path)?.len())
}

/// Append one row. The chain continues from the last row in the file.
pub fn append(path: &Path, ts: &str, kind: &str, body: Json) -> Result<Row, String> {
    let rows = read(path)?;
    let (seq, prev) = match rows.last() {
        Some(last) => (last.seq + 1, last.hash.clone()),
        None => (0, GENESIS.to_string()),
    };
    let mut row = Row {
        seq,
        ts: ts.to_string(),
        kind: kind.to_string(),
        body,
        prev,
        hash: String::new(),
    };
    row.hash = row.compute_hash();

    if let Some(dir) = path.parent() {
        if !dir.as_os_str().is_empty() {
            std::fs::create_dir_all(dir)
                .map_err(|e| format!("cannot create {}: {}", dir.display(), e))?;
        }
    }
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .map_err(|e| format!("cannot open ledger {}: {}", path.display(), e))?;
    let line = format!("{}\n", row.to_json().to_text());
    file.write_all(line.as_bytes())
        .map_err(|e| format!("cannot write ledger {}: {}", path.display(), e))?;
    file.flush()
        .map_err(|e| format!("cannot flush ledger {}: {}", path.display(), e))?;
    Ok(row)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::json::Json;

    fn tmp(name: &str) -> PathBuf {
        let mut p = std::env::temp_dir();
        p.push(format!("gc-test-{}-{}", std::process::id(), name));
        let _ = std::fs::remove_file(&p);
        p
    }

    #[test]
    fn append_then_verify() {
        let path = tmp("append");
        append(&path, "2026-11-02T10:00:00Z", "job.new", Json::obj()).unwrap();
        append(&path, "2026-11-02T10:01:00Z", "close", Json::obj()).unwrap();
        assert_eq!(verify(&path).unwrap(), 2);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn tamper_is_caught() {
        let path = tmp("tamper");
        append(&path, "2026-11-02T10:00:00Z", "job.new", Json::obj()).unwrap();
        append(&path, "2026-11-02T10:01:00Z", "close", Json::obj()).unwrap();
        let text = std::fs::read_to_string(&path).unwrap();
        let tampered = text.replace("\"seq\":1", "\"seq\":9");
        std::fs::write(&path, tampered).unwrap();
        assert!(verify(&path).is_err());
        let _ = std::fs::remove_file(&path);
    }
}
