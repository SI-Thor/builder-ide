//! Timestamps without a crate: ISO-8601 in, ISO-8601 out, UTC only.
//!
//! The ledger needs one time format and one time zone. Keeping the conversion
//! here means the rest of the program never touches a calendar.

use std::time::{SystemTime, UNIX_EPOCH};

/// The current time as "YYYY-MM-DDTHH:MM:SSZ".
///
/// `GC_NOW` (unix seconds) overrides the clock. That is what makes the ledger
/// reproducible: the same commands with the same `GC_NOW` write byte-identical
/// rows.
pub fn now_iso() -> String {
    let secs = match std::env::var("GC_NOW") {
        Ok(v) => v.trim().parse::<i64>().unwrap_or_else(|_| unix_now()),
        Err(_) => unix_now(),
    };
    format_iso(secs)
}

fn unix_now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Format unix seconds as "YYYY-MM-DDTHH:MM:SSZ".
pub fn format_iso(secs: i64) -> String {
    let days = secs.div_euclid(86400);
    let rem = secs.rem_euclid(86400);
    let (y, m, d) = civil_from_days(days);
    format!(
        "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}Z",
        y,
        m,
        d,
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// Parse "YYYY-MM-DDTHH:MM:SSZ" (also accepts a space separator and a
/// missing seconds field) into unix seconds.
#[allow(dead_code)]
pub fn parse_iso(text: &str) -> Result<i64, String> {
    let t = text.trim();
    if t.len() < 10 {
        return Err(format!("bad timestamp '{}': expected YYYY-MM-DDTHH:MM:SSZ", text));
    }
    let num = |a: usize, b: usize| -> Result<i64, String> {
        t.get(a..b)
            .and_then(|s| s.parse::<i64>().ok())
            .ok_or_else(|| format!("bad timestamp '{}'", text))
    };
    let year = num(0, 4)?;
    let month = num(5, 7)?;
    let day = num(8, 10)?;
    let hour = if t.len() >= 13 { num(11, 13)? } else { 0 };
    let minute = if t.len() >= 16 { num(14, 16)? } else { 0 };
    let second = if t.len() >= 19 { num(17, 19)? } else { 0 };
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return Err(format!("bad timestamp '{}'", text));
    }
    Ok(days_from_civil(year, month as u32, day as u32) * 86400 + hour * 3600 + minute * 60 + second)
}

/// Days since 1970-01-01 for a civil date (Howard Hinnant's algorithm).
#[allow(dead_code)]
pub fn days_from_civil(y: i64, m: u32, d: u32) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = (y - era * 400) as u64; // [0, 399]
    let mp = if m > 2 { m - 3 } else { m + 9 } as u64; // [0, 11]
    let doy = (153 * mp + 2) / 5 + d as u64 - 1; // [0, 365]
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy; // [0, 146096]
    era * 146097 + doe as i64 - 719468
}

/// Civil date from days since 1970-01-01.
pub fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719468;
    let era = if z >= 0 { z } else { z - 146096 } / 146097;
    let doe = (z - era * 146097) as u64; // [0, 146096]
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; // [0, 399]
    let y = yoe as i64 + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100); // [0, 365]
    let mp = (5 * doy + 2) / 153; // [0, 11]
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32; // [1, 31]
    let m = if mp < 10 { mp + 3 } else { mp - 9 } as u32; // [1, 12]
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats_a_known_instant() {
        assert_eq!(format_iso(0), "1970-01-01T00:00:00Z");
        assert_eq!(format_iso(1762077600), "2025-11-02T10:00:00Z");
    }

    #[test]
    fn round_trips() {
        let iso = "2026-11-02T09:59:00Z";
        let secs = parse_iso(iso).unwrap();
        assert_eq!(format_iso(secs), iso);
    }

    #[test]
    fn parses_dates_without_a_time() {
        assert_eq!(format_iso(parse_iso("2026-11-02").unwrap()), "2026-11-02T00:00:00Z");
    }
}
