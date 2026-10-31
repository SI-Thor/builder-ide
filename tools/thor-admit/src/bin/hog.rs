//! `thor-admit-hog` — a synthetic memory hog.
//!
//! It exists so the admission rule and the watchdog can be tested without
//! running a real model. It allocates on the **CPU only** (no CUDA, no GPU),
//! faults the pages in so the kernel really accounts for them, and holds.
//!
//! ```text
//! thor-admit-hog --bytes 30G --hold 10
//! ```

use std::process::ExitCode;
use std::time::{Duration, Instant};

fn parse_bytes(text: &str) -> Option<u64> {
    let split = text
        .find(|c: char| !(c.is_ascii_digit() || c == '.'))
        .unwrap_or(text.len());
    let (number, unit) = text.split_at(split);
    let value: f64 = number.parse().ok()?;
    let multiplier = match unit.trim().to_ascii_lowercase().as_str() {
        "" | "b" => 1u64,
        "k" | "kb" | "kib" => 1024,
        "m" | "mb" | "mib" => 1024 * 1024,
        "g" | "gb" | "gib" => 1024 * 1024 * 1024,
        "t" | "tb" | "tib" => 1024u64 * 1024 * 1024 * 1024,
        _ => return None,
    };
    Some((value * multiplier as f64).round() as u64)
}

fn main() -> ExitCode {
    let mut bytes: u64 = 1024 * 1024 * 1024;
    let mut hold = Duration::from_secs(5);
    let mut args = std::env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--bytes" => match args.next().and_then(|v| parse_bytes(&v)) {
                Some(value) => bytes = value,
                None => {
                    eprintln!("--bytes needs a size (40G)");
                    return ExitCode::from(2);
                }
            },
            "--hold" => match args.next().and_then(|v| v.parse::<f64>().ok()) {
                Some(seconds) => hold = Duration::from_secs_f64(seconds),
                None => {
                    eprintln!("--hold needs a number of seconds");
                    return ExitCode::from(2);
                }
            },
            "--help" | "-h" => {
                println!("thor-admit-hog --bytes <size> --hold <seconds>");
                return ExitCode::SUCCESS;
            }
            other => {
                eprintln!("unknown argument {other:?}");
                return ExitCode::from(2);
            }
        }
    }

    let started = Instant::now();
    // Fault every page in, so the kernel's accounting sees the whole thing.
    let mut memory = vec![0u8; bytes as usize];
    let page = 4096;
    let mut index = 0usize;
    while index < memory.len() {
        memory[index] = (index / page) as u8;
        index += page;
    }
    let faulted = Instant::now();
    println!(
        "hog: holding {} MiB, faulted in {:.2}s, pid {}",
        bytes / (1024 * 1024),
        faulted.duration_since(started).as_secs_f64(),
        std::process::id()
    );

    let deadline = Instant::now() + hold;
    while Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(100));
    }

    let hwm = std::fs::read_to_string(format!("/proc/{}/status", std::process::id()))
        .ok()
        .and_then(|text| {
            text.lines().find_map(|line| {
                line.strip_prefix("VmHWM:")
                    .and_then(|rest| rest.split_whitespace().next())
                    .and_then(|value| value.parse::<u64>().ok())
                    .map(|kb| kb * 1024)
            })
        })
        .unwrap_or(0);
    println!(
        "hog: done, peak RSS {} MiB after {:.2}s",
        hwm / (1024 * 1024),
        started.elapsed().as_secs_f64()
    );
    // Keep the memory alive until here so the peak is real.
    std::hint::black_box(&mut memory);
    ExitCode::SUCCESS
}
