//! The pose stream: an emitter that sends each subscriber only what its interest region
//! needs, and projectors that rebuild the world exactly from that stream.
//!
//! Run `posestream` to reproduce RESULT.json (see bench.sh).

mod bench;
mod budget;
mod net;
mod space;
mod stream;
mod wire;
mod world;

use net::NetConfig;
use stream::Mode;
use std::env;

fn usage() {
    eprintln!(
        "usage: posestream [--seed N] [--ticks N] [--mode direct|predictive] [--out RESULT.json] \
         [--log bench_log.txt] [--team mcode]\n\
         \n\
         the network (the default is the loopback: no delay, no loss)\n\
         \x20 --net on|off            the lossy delayed link\n\
         \x20 --delay-min MS          the smallest one-way delay (default 2)\n\
         \x20 --delay-max MS          the largest one-way delay (default 12)\n\
         \x20 --jitter MS             the jitter around it, +/- (default 1.5)\n\
         \x20 --loss P                the probability that a packet is lost (default 0.005)\n\
         \n\
         the carried-over ideas\n\
         \x20 --backdate on|off       the receiver back-dates the correction (default on)\n\
         \x20 --hysteresis M          the exit hysteresis on the interest regions (default 0)\n\
         \x20 --evict2 on|off         the leave list as absolute 16-bit ids (default off)"
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
    // the network the brief asks for; `--net off` is the loopback
    let mut net = NetConfig::standard(0.005);
    net.enabled = false;
    let mut backdate = true;
    let mut hysteresis: f64 = 0.0;
    let mut evict_abs = false;

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
            "--net" => {
                net.enabled = match args[i + 1].as_str() {
                    "on" | "true" | "yes" => true,
                    "off" | "false" | "no" => false,
                    other => {
                        eprintln!("--net wants on|off, got {}", other);
                        std::process::exit(2);
                    }
                };
                i += 2;
            }
            "--delay-min" => {
                net.delay_min_ms = args[i + 1].parse().expect("delay-min");
                i += 2;
            }
            "--delay-max" => {
                net.delay_max_ms = args[i + 1].parse().expect("delay-max");
                i += 2;
            }
            "--jitter" => {
                net.jitter_ms = args[i + 1].parse().expect("jitter");
                i += 2;
            }
            "--loss" => {
                net.loss = args[i + 1].parse().expect("loss");
                i += 2;
            }
            "--backdate" => {
                backdate = match args[i + 1].as_str() {
                    "on" | "true" | "yes" => true,
                    "off" | "false" | "no" => false,
                    other => {
                        eprintln!("--backdate wants on|off, got {}", other);
                        std::process::exit(2);
                    }
                };
                i += 2;
            }
            "--hysteresis" => {
                hysteresis = args[i + 1].parse().expect("hysteresis");
                i += 2;
            }
            "--evict2" => {
                evict_abs = match args[i + 1].as_str() {
                    "on" | "true" | "yes" => true,
                    "off" | "false" | "no" => false,
                    other => {
                        eprintln!("--evict2 wants on|off, got {}", other);
                        std::process::exit(2);
                    }
                };
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
        net,
        backdate,
        hysteresis,
        evict_abs,
    };
    let report = bench::run(&cfg);
    std::fs::write(&cfg.log_path, &report.log).expect("write log");
    bench::write_result(&cfg.out_path, &report, &team, &cfg).expect("write result");

    println!(
        "bytes/s/sub  mean {:.1}  p95 {:.1}  (sent {:.1})\nemitter ms/tick  p50 {:.4}  p95 {:.4}  \
         (own work p50 {:.4} p95 {:.4})\n\
         delivery latency p95 {:.4} ms\nreconstruction errors {}\n\
         mirror mismatches {}\nlate join resync {:.4} ms\nresyncs {}  keyframes {}\n\
         packets {} sent, {} lost\nwrote {} and {}",
        report.bytes_mean,
        report.bytes_p95,
        report.bytes_sent_mean,
        report.emitter_p50,
        report.emitter_p95,
        report.emitter_work_p50,
        report.emitter_work_p95,
        report.latency_p95,
        report.errors,
        report.mirror_mismatches,
        report.late_join_resync_ms,
        report.resyncs,
        report.keyframes,
        report.packets_sent,
        report.packets_lost,
        cfg.out_path,
        cfg.log_path
    );
}
