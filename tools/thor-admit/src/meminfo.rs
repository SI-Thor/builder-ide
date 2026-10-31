//! The kernel's own memory accounting, read from `/proc/meminfo`.
//!
//! `MemAvailable` is the number the admission rule uses: it is the kernel's
//! estimate of how much memory a new allocation could get without swapping
//! (there is no swap on this box) and without reclaiming aggressively.

use std::fmt;
use std::io;
use std::path::Path;

/// The fields of `/proc/meminfo` the daemon uses, in bytes.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct MemInfo {
    pub mem_total: u64,
    pub mem_free: u64,
    pub mem_available: u64,
    pub buffers: u64,
    pub cached: u64,
    pub swap_total: u64,
    pub swap_free: u64,
}

impl MemInfo {
    /// Read `/proc/meminfo`.
    pub fn read() -> io::Result<MemInfo> {
        MemInfo::read_from(Path::new("/proc/meminfo"))
    }

    /// Read a meminfo file (the tests point this at a fixture).
    pub fn read_from(path: &Path) -> io::Result<MemInfo> {
        let text = std::fs::read_to_string(path)?;
        MemInfo::parse(&text).map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))
    }

    /// Parse the contents of a meminfo file.
    pub fn parse(text: &str) -> Result<MemInfo, MemInfoError> {
        let mut info = MemInfo::default();
        for line in text.lines() {
            let Some((key, value)) = line.split_once(':') else {
                continue;
            };
            let kb = parse_kb(value).ok_or_else(|| MemInfoError::MalformedLine(line.to_string()))?;
            let bytes = kb * 1024;
            match key.trim() {
                "MemTotal" => info.mem_total = bytes,
                "MemFree" => info.mem_free = bytes,
                "MemAvailable" => info.mem_available = bytes,
                "Buffers" => info.buffers = bytes,
                "Cached" => info.cached = bytes,
                "SwapTotal" => info.swap_total = bytes,
                "SwapFree" => info.swap_free = bytes,
                _ => {}
            }
        }
        if info.mem_total == 0 {
            return Err(MemInfoError::NoMemTotal);
        }
        Ok(info)
    }

    /// The memory a new allocation could take without the kernel reclaiming
    /// hard: the total minus what is already spoken for.
    pub fn used(&self) -> u64 {
        self.mem_total.saturating_sub(self.mem_available)
    }
}

fn parse_kb(value: &str) -> Option<u64> {
    let first = value.split_whitespace().next()?;
    first.parse::<u64>().ok()
}

/// Why a meminfo file could not be read.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MemInfoError {
    MalformedLine(String),
    NoMemTotal,
}

impl fmt::Display for MemInfoError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MemInfoError::MalformedLine(line) => write!(f, "cannot read meminfo line {line:?}"),
            MemInfoError::NoMemTotal => write!(f, "the meminfo file has no MemTotal"),
        }
    }
}

impl std::error::Error for MemInfoError {}

#[cfg(test)]
mod tests {
    use super::*;

    const FIXTURE: &str = "\
MemTotal:       128766532 kB
MemFree:        115304760 kB
MemAvailable:   118252692 kB
Buffers:          572836 kB
Cached:          3298136 kB
SwapCached:            0 kB
SwapTotal:             0 kB
SwapFree:              0 kB
HugePages_Total:       0
";

    #[test]
    fn reads_the_fields_the_rule_uses() {
        let info = MemInfo::parse(FIXTURE).unwrap();
        assert_eq!(info.mem_total, 128766532 * 1024);
        assert_eq!(info.mem_available, 118252692 * 1024);
        assert_eq!(info.mem_free, 115304760 * 1024);
        assert_eq!(info.swap_total, 0);
    }

    #[test]
    fn used_is_total_minus_available() {
        let info = MemInfo::parse(FIXTURE).unwrap();
        assert_eq!(info.used(), info.mem_total - info.mem_available);
    }

    #[test]
    fn a_file_without_mem_total_is_refused() {
        assert_eq!(
            MemInfo::parse("MemFree: 1 kB\n").unwrap_err(),
            MemInfoError::NoMemTotal
        );
    }

    #[test]
    fn a_line_that_is_not_a_size_is_refused() {
        assert!(matches!(
            MemInfo::parse("MemTotal: lots kB\n").unwrap_err(),
            MemInfoError::MalformedLine(_)
        ));
    }

    #[test]
    fn reads_the_real_kernel_file() {
        let info = MemInfo::read().unwrap();
        assert!(info.mem_total > 100 * 1024 * 1024 * 1024, "the Thor has 122 GiB");
        assert!(info.mem_available <= info.mem_total);
    }
}
