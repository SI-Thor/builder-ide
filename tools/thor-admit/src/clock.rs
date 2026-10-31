//! UTC timestamps, in the format the project's records use (RFC 3339).
//!
//! The daemon writes times into its log and into the peak history; the cost
//! model's records are RFC 3339 UTC, so the same format is used here.

use std::time::{SystemTime, UNIX_EPOCH};

/// Seconds since the Unix epoch, right now.
pub fn unix_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// The current time as RFC 3339 UTC, with milliseconds.
pub fn rfc3339_now() -> String {
    rfc3339(unix_seconds())
}

/// Format a Unix timestamp as RFC 3339 UTC.
pub fn rfc3339(seconds: u64) -> String {
    let days = (seconds / 86_400) as i64;
    let rest = seconds % 86_400;
    let (year, month, day) = civil_from_days(days);
    format!(
        "{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z",
        rest / 3600,
        (rest % 3600) / 60,
        rest % 60
    )
}

/// The civil date for a day count since 1970-01-01 (Howard Hinnant's
/// `civil_from_days`).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m as u32, d as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_epoch_is_the_epoch() {
        assert_eq!(rfc3339(0), "1970-01-01T00:00:00Z");
    }

    #[test]
    fn a_known_moment() {
        // 2026-10-31T13:36:00Z
        assert_eq!(rfc3339(1_793_453_760), "2026-10-31T13:36:00Z");
    }

    #[test]
    fn a_leap_day() {
        // 2024-02-29T00:00:00Z
        assert_eq!(rfc3339(1_709_164_800), "2024-02-29T00:00:00Z");
    }

    #[test]
    fn now_is_after_the_box_was_bought() {
        assert!(unix_seconds() > 1_700_000_000);
    }
}
