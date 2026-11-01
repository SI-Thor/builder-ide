//! The pose stream: an emitter that sends each subscriber only what its interest region
//! needs, and projectors that rebuild the world exactly from that stream.
//!
//! Run `posestream` to reproduce RESULT.json (see bench.sh).

mod bench;
mod space;
mod stream;
mod wire;
mod world;

use stream::Mode;
use std::env;

fn usage() {
    eprintln!(
        "usage: posestream [--seed N] [--ticks N] [--mode direct|predictive] [--out RESULT.json] [--log bench_log.txt] [--team mcode]"
    );
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let mut seed: u64 = 0xBEEF_CAFE_1234;
    let mut ticks: u32 = 3600;
    let mut out = "RESULT.json".to_string();
    let mut log = "bench_log.txt".to_string();
    let mut team = "mcode".to_string();
    let mut mode = Mode::Predictive;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--seed" => {
                seed = args[i + 1].parse().expect("seed");
                i += 2;
            }
            "--ticks" => {
                ticks = args[i + 1].parse().expect("ticks");
                i += 2;
            }
            "--out" => {
                out = args[i + 1].clone();
                i += 2;
            }
            "--log" => {
                log = args[i + 1].clone();
                i += 2;
            }
            "--mode" => {
                mode = match args[i + 1].as_str() {
                    "direct" => Mode::Direct,
                    "predictive" => Mode::Predictive,
                    other => {
                        eprintln!("unknown mode: {}", other);
                        usage();
                        std::process::exit(2);
                    }
                };
                i += 2;
            }
            "--team" => {
                team = args[i + 1].clone();
                i += 2;
            }
            "-h" | "--help" => {
                usage();
                return;
            }
            other => {
                eprintln!("unknown argument: {}", other);
                usage();
                std::process::exit(2);
            }
        }
    }

    let cfg = bench::Config {
        seed,
        ticks,
        out_path: out,
        log_path: log,
        mode,
    };
    let report = bench::run(&cfg);
    std::fs::write(&cfg.log_path, &report.log).expect("write log");
    bench::write_result(&cfg.out_path, &report, &team).expect("write result");

    println!(
        "bytes/s/sub  mean {:.1}  p95 {:.1}\nemitter ms/tick  p50 {:.4}  p95 {:.4}\n\
         delivery latency p95 {:.4} ms\nreconstruction errors {}\nlate join resync {:.4} ms\n\
         wrote {} and {}",
        report.bytes_mean,
        report.bytes_p95,
        report.emitter_p50,
        report.emitter_p95,
        report.latency_p95,
        report.errors,
        report.late_join_resync_ms,
        cfg.out_path,
        cfg.log_path
    );
}
