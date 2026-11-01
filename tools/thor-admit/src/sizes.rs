//! Sizes the operator writes on the command line: `40G`, `1.5GiB`, `512M`.
//!
//! The unit is bytes everywhere inside the daemon; this module is the only
//! place a human unit is allowed to exist.

use std::fmt;

/// A size in bytes, with the way it was written kept for the log.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Size {
    pub bytes: u64,
}

impl Size {
    pub fn from_bytes(bytes: u64) -> Self {
        Size { bytes }
    }

    /// Parse a size the operator wrote.
    ///
    /// Accepted: `40G`, `40GB`, `40GiB`, `40g`, `1.5G`, `512M`, `512MiB`,
    /// and a bare number, which is bytes.
    pub fn parse(text: &str) -> Result<Size, SizeError> {
        let raw = text.trim();
        if raw.is_empty() {
            return Err(SizeError::Empty);
        }
        let split = raw
            .find(|c: char| !(c.is_ascii_digit() || c == '.'))
            .unwrap_or(raw.len());
        let (number, unit) = raw.split_at(split);
        let number = number.trim();
        if number.is_empty() {
            return Err(SizeError::Malformed(text.to_string()));
        }
        let value: f64 = number
            .parse()
            .map_err(|_| SizeError::Malformed(text.to_string()))?;
        if !value.is_finite() || value < 0.0 {
            return Err(SizeError::Malformed(text.to_string()));
        }
        let multiplier = unit_multiplier(unit).ok_or_else(|| SizeError::UnknownUnit(unit.to_string()))?;
        let bytes = value * multiplier as f64;
        if !bytes.is_finite() || bytes < 0.0 || bytes > u64::MAX as f64 {
            return Err(SizeError::Malformed(text.to_string()));
        }
        Ok(Size {
            bytes: bytes.round() as u64,
        })
    }
}

fn unit_multiplier(unit: &str) -> Option<u64> {
    match unit.trim().to_ascii_lowercase().as_str() {
        "" | "b" => Some(1),
        "k" | "kb" | "kib" => Some(1024),
        "m" | "mb" | "mib" => Some(1024 * 1024),
        "g" | "gb" | "gib" => Some(1024 * 1024 * 1024),
        "t" | "tb" | "tib" => Some(1024u64 * 1024 * 1024 * 1024),
        _ => None,
    }
}

/// Why a size could not be read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SizeError {
    Empty,
    Malformed(String),
    UnknownUnit(String),
}

impl fmt::Display for SizeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            SizeError::Empty => write!(f, "a size cannot be empty"),
            SizeError::Malformed(text) => write!(f, "cannot read {text:?} as a size"),
            SizeError::UnknownUnit(unit) => {
                write!(f, "unknown size unit {unit:?} (use B, K, M, G or T)")
            }
        }
    }
}

impl std::error::Error for SizeError {}

/// Render a byte count the way an operator reads it: `40.0G`.
pub fn human(bytes: u64) -> String {
    const UNITS: [(&str, u64); 4] = [
        ("T", 1024 * 1024 * 1024 * 1024),
        ("G", 1024 * 1024 * 1024),
        ("M", 1024 * 1024),
        ("K", 1024),
    ];
    for (name, factor) in UNITS {
        if bytes >= factor {
            let value = bytes as f64 / factor as f64;
            return format!("{value:.1}{name}");
        }
    }
    format!("{bytes}B")}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_plain_gigabytes() {
        assert_eq!(Size::parse("40G").unwrap().bytes, 40 * 1024 * 1024 * 1024);
        assert_eq!(Size::parse("40GB").unwrap().bytes, 40 * 1024 * 1024 * 1024);
        assert_eq!(Size::parse("40GiB").unwrap().bytes, 40 * 1024 * 1024 * 1024);
        assert_eq!(Size::parse(" 40g ").unwrap().bytes, 40 * 1024 * 1024 * 1024);
    }

    #[test]
    fn parses_fractional_and_small_units() {
        assert_eq!(Size::parse("1.5G").unwrap().bytes, 1610612736);
        assert_eq!(Size::parse("512M").unwrap().bytes, 536870912);
        assert_eq!(Size::parse("64K").unwrap().bytes, 65536);
    }

    #[test]
    fn a_bare_number_is_bytes() {
        assert_eq!(Size::parse("1024").unwrap().bytes, 1024);
        assert_eq!(Size::parse("0").unwrap().bytes, 0);
    }

    #[test]
    fn rejects_nonsense() {
        assert_eq!(Size::parse("").unwrap_err(), SizeError::Empty);
        assert_eq!(
            Size::parse("40Q").unwrap_err(),
            SizeError::UnknownUnit("Q".to_string())
        );
        assert!(matches!(
            Size::parse("forty").unwrap_err(),
            SizeError::Malformed(_)
        ));
        assert!(matches!(
            Size::parse("-5G").unwrap_err(),
            SizeError::Malformed(_)
        ));
    }

    #[test]
    fn human_reads_the_way_an_operator_does() {
        assert_eq!(human(40 * 1024 * 1024 * 1024), "40.0G");
        assert_eq!(human(512 * 1024 * 1024), "512.0M");
        assert_eq!(human(900), "900B");
    }
}
