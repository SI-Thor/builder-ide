//! End-to-end tests: run the real `gc` binary and check what it writes.
//!
//! Every test drives the program the way a seat or the general contractor
//! would, so the ledger, the report and the refusals are all exercised
//! through the same code path.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicUsize, Ordering};

static COUNTER: AtomicUsize = AtomicUsize::new(0);

fn workdir(name: &str) -> PathBuf {
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    let mut p = std::env::temp_dir();
    p.push(format!(
        "gc-test-{}-{}-{}",
        std::process::id(),
        name,
        n
    ));
    let _ = std::fs::remove_dir_all(&p);
    std::fs::create_dir_all(&p).expect("cannot make the test directory");
    p
}

fn gc(dir: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_gc"))
        .current_dir(dir)
        .args(args)
        .env("GC_NOW", "1793640000") // 2026-11-02T10:40:00Z: a fixed clock
        .output()
        .expect("cannot run gc")
}

fn ok(dir: &Path, args: &[&str]) -> String {
    let out = gc(dir, args);
    assert!(
        out.status.success(),
        "gc {:?} failed: {}",
        args,
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).to_string()
}

fn fails(dir: &Path, args: &[&str]) -> String {
    let out = gc(dir, args);
    assert!(
        !out.status.success(),
        "gc {:?} should have failed but printed: {}",
        args,
        String::from_utf8_lossy(&out.stdout)
    );
    String::from_utf8_lossy(&out.stderr).to_string()
}

/// Write one finished job by hand: a job, a bid by `sub`, and a close with
/// the given actual crew-time. The bid is hand-made (not computed), so the
/// test controls the track record exactly.
fn finished_job(dir: &Path, class: &str, sub: &str, bid_min: f64, actual_min: f64, accepted: bool) {
    let estimate = 100.0;
    ok(
        dir,
        &[
            "job", "new", "--title", "t", "--class", class, "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
        ],
    );
    let list = ok(dir, &["job", "list"]);
    let job_id = list
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .expect("no job id")
        .to_string();
    ok(
        dir,
        &[
            "bid", "--job", &job_id, "--sub", sub, "--crew-min", &format!("{}", bid_min),
            "--submit",
        ],
    );
    let bids = ok(dir, &["job", "list"]);
    let _ = bids;
    let bid_id = bid_id_of(dir, &job_id);
    ok(dir, &["award", "--job", &job_id, "--bid", &bid_id]);
    let actual = format!("{}", actual_min);
    let mut args = vec!["close", "--job", &job_id, "--crew-min", actual.as_str()];
    if accepted {
        args.push("--accepted");
    } else {
        args.push("--failed");
    }
    ok(dir, &args);
    let _ = estimate;
}

/// The id of the first bid on a job: the ledger is append-only, so the first
/// bid row for the job is the oldest.
fn bid_id_of(dir: &Path, job_id: &str) -> String {
    let ledger = std::fs::read_to_string(dir.join("ledger.jsonl")).expect("no ledger");
    for line in ledger.lines() {
        if !line.contains("\"kind\":\"bid.new\"") {
            continue;
        }
        if !line.contains(&format!("\"job_id\":\"{}\"", job_id)) {
            continue;
        }
        // The id is the first field of the body.
        if let Some(at) = line.find("\"id\":\"") {
            let rest = &line[at + 6..];
            let end = rest.find('"').unwrap();
            return rest[..end].to_string();
        }
    }
    panic!("no bid for {}", job_id);
}

#[test]
fn the_ledger_is_a_hash_chain_and_tampering_shows() {
    let dir = workdir("chain");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "lab-experiment", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let verified = ok(&dir, &["verify"]);
    assert!(verified.contains("chain intact"), "{}", verified);

    // Change one byte of a row: the chain must stop verifying.
    let path = dir.join("ledger.jsonl");
    let text = std::fs::read_to_string(&path).unwrap();
    let tampered = text.replace("\"scope\":\"s\"", "\"scope\":\"x\"");
    assert_ne!(text, tampered, "the test did not change anything");
    std::fs::write(&path, tampered).unwrap();

    let err = fails(&dir, &["verify"]);
    assert!(
        err.contains("hash does not match"),
        "a changed row should not verify: {}",
        err
    );
}

#[test]
fn the_bid_is_calibrated_from_the_track_record() {
    let dir = workdir("calibration");

    // Three clean runs of 40, 50 and 60 minutes on one class.
    for actual in [40.0, 50.0, 60.0] {
        finished_job(&dir, "lab-experiment", "mcode", 100.0, actual, true);
    }

    // A new job with the GC's estimate of 100 minutes.
    ok(
        &dir,
        &[
            "job", "new", "--title", "new", "--class", "lab-experiment", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
        ],
    );
    let list = ok(&dir, &["job", "list"]);
    let job_id = list
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .unwrap()
        .to_string();

    let bid = ok(&dir, &["bid", "--job", &job_id, "--sub", "mcode"]);
    // median 50, q80 = 50 + 0.6 * (60 - 50) = 56, raw factor 1.12,
    // shrunk toward the prior 1.25 with weight 2: (3*1.12 + 2*1.25)/5 = 1.172,
    // so the bid is 117 crew-minutes over a 100-minute estimate.
    assert!(
        bid.contains("117 crew-min"),
        "the calibrated bid should be 117 crew-minutes:\n{}",
        bid
    );
    assert!(
        bid.contains("3 clean runs"),
        "the bid should say where the factor came from:\n{}",
        bid
    );

    // A seat with no history gets the prior: 100 * 1.25 = 125.
    let prior = ok(&dir, &["bid", "--job", &job_id, "--sub", "zcode"]);
    assert!(
        prior.contains("125 crew-min"),
        "a seat with no history should get the prior bid:\n{}",
        prior
    );
    assert!(prior.contains("no finished run"), "{}", prior);
}

#[test]
fn closing_a_job_moves_money_and_carries_debt() {
    let dir = workdir("debt");

    // One job: the promise is 60 minutes, the seat takes 90, and it is a
    // day late.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "merge-fix", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
            "--penalty-per-day-min", "30",
        ],
    );
    let job = ok(&dir, &["job", "list"])
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .unwrap()
        .to_string();
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    let bid = bid_id_of(&dir, &job);
    ok(&dir, &["award", "--job", &job, "--bid", &bid]);

    // 90 crew-minutes against a 60-minute promise, and 2880 job-minutes
    // against a 1440-minute deadline: one day late.
    let closed = ok(
        &dir,
        &[
            "close", "--job", &job, "--crew-min", "90", "--job-min", "2880", "--accepted",
        ],
    );
    assert!(closed.contains("overrun 30"), "{}", closed);
    assert!(closed.contains("penalty 30"), "{}", closed);
    assert!(closed.contains("debt +60"), "{}", closed);

    // A second job the seat finishes early repays 20 of the 60.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t2", "--class", "merge-fix", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
            "--penalty-per-day-min", "30",
        ],
    );
    let job2 = ok(&dir, &["job", "list"])
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .unwrap()
        .to_string();
    ok(&dir, &["bid", "--job", &job2, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    let bid2 = bid_id_of(&dir, &job2);
    ok(&dir, &["award", "--job", &job2, "--bid", &bid2]);
    let closed2 = ok(
        &dir,
        &["close", "--job", &job2, "--crew-min", "40", "--accepted"],
    );
    assert!(closed2.contains("debt -20"), "{}", closed2);

    // The book shows 40 crew-minutes of debt left.
    let report = ok(&dir, &["report", "--json"]);
    assert!(
        report.contains("\"debt_min\":40"),
        "the seat should carry 40 crew-minutes of debt:\n{}",
        report
    );
}

#[test]
fn the_stop_rule_stops_the_burn_until_the_gc_re_scopes() {
    let dir = workdir("stop");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
        ],
    );
    let job = ok(&dir, &["job", "list"])
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .unwrap()
        .to_string();
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "100", "--submit"]);
    let bid = bid_id_of(&dir, &job);
    ok(&dir, &["award", "--job", &job, "--bid", &bid]);

    // 80% of the bid without the goal line: the seat must stop.
    let cp = ok(&dir, &["checkpoint", "--job", &job, "--crew-used-min", "80"]);
    assert!(cp.contains("STOP REQUIRED"), "{}", cp);

    // More burn is refused until the general contractor re-scopes.
    let err = fails(&dir, &["checkpoint", "--job", &job, "--crew-used-min", "90"]);
    assert!(err.contains("stopped at"), "{}", err);

    // A change order lifts the stop.
    ok(
        &dir,
        &[
            "change-order", "--job", &job, "--reason", "scope grew",
            "--add-crew-min", "60", "--add-job-min", "600",
        ],
    );
    ok(&dir, &["checkpoint", "--job", &job, "--crew-used-min", "90"]);

    // The promise moved with the change order: 100 + 60 = 160.
    let closed = ok(&dir, &["close", "--job", &job, "--crew-min", "120", "--accepted"]);
    assert!(closed.contains("against a promise of 160"), "{}", closed);
}

#[test]
fn a_seat_in_deep_debt_is_not_hired_until_it_is_retooled() {
    let dir = workdir("retool");

    // A seat that overruns twice: 150 minutes against a 60-minute promise
    // is 90 minutes of debt each time.
    for _ in 0..2 {
        ok(
            &dir,
            &[
                "job", "new", "--title", "t", "--class", "lab-experiment", "--scope", "s",
                "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
            ],
        );
        let job = ok(&dir, &["job", "list"])
            .lines()
            .last()
            .and_then(|l| l.split_whitespace().next())
            .unwrap()
            .to_string();
        ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "60", "--submit"]);
        let bid = bid_id_of(&dir, &job);
        ok(&dir, &["award", "--job", &job, "--bid", &bid]);
        ok(&dir, &["close", "--job", &job, "--crew-min", "150", "--accepted"]);
    }

    // A new job: the seat may not be awarded it.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t3", "--class", "lab-experiment", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let job = ok(&dir, &["job", "list"])
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .unwrap()
        .to_string();
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    let bid = bid_id_of(&dir, &job);

    let err = fails(&dir, &["award", "--job", &job, "--bid", &bid]);
    assert!(err.contains("deep debt"), "{}", err);

    // Retool it, and the award goes through.
    ok(
        &dir,
        &[
            "retool", "--sub", "zcode", "--class", "lab-experiment",
            "--reason", "the seat quoted 60 and took 150", "--action", "smaller jobs",
        ],
    );
    ok(&dir, &["award", "--job", &job, "--bid", &bid]);
}

#[test]
fn the_same_commands_write_the_same_ledger() {
    let script: Vec<Vec<&str>> = vec![
        vec![
            "job", "new", "--title", "t", "--class", "lab-experiment", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
        ],
        vec!["job", "list"],
    ];

    let mut ledgers: Vec<String> = Vec::new();
    let mut reports: Vec<String> = Vec::new();
    for _ in 0..2 {
        let dir = workdir("determinism");
        for args in &script {
            ok(&dir, args);
        }
        // A bid and a close, with the clock fixed by GC_NOW.
        let job = ok(&dir, &["job", "list"])
            .lines()
            .last()
            .and_then(|l| l.split_whitespace().next())
            .unwrap()
            .to_string();
        ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "120", "--submit"]);
        let bid = bid_id_of(&dir, &job);
        ok(&dir, &["award", "--job", &job, "--bid", &bid]);
        ok(&dir, &["close", "--job", &job, "--crew-min", "90", "--accepted"]);

        ledgers.push(std::fs::read_to_string(dir.join("ledger.jsonl")).unwrap());
        reports.push(ok(&dir, &["report"]));
    }

    assert_eq!(
        ledgers[0], ledgers[1],
        "the same commands must write the same ledger bytes"
    );
    assert_eq!(reports[0], reports[1], "the report must be the same");
}

#[test]
fn the_brief_block_states_the_terms() {
    let dir = workdir("brief");
    ok(
        &dir,
        &[
            "job", "new", "--title", "lay carpet", "--class", "build-feature",
            "--scope", "lay 40 square metres of carpet",
            "--accept-cmd", "cargo test", "--estimate-min", "120", "--deadline-min", "600",
            "--penalty-per-day-min", "45",
        ],
    );
    let job = ok(&dir, &["job", "list"])
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .unwrap()
        .to_string();
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "120", "--submit"]);
    let bid = bid_id_of(&dir, &job);
    ok(&dir, &["award", "--job", &job, "--bid", &bid]);

    let brief = ok(&dir, &["brief", "--job", &job]);
    assert!(brief.contains("lay 40 square metres"), "{}", brief);
    assert!(brief.contains("`cargo test` exits 0"), "{}", brief);
    assert!(brief.contains("Your bid:"), "{}", brief);
    assert!(brief.contains("Stop rule"), "{}", brief);
    assert!(brief.contains("45 crew-minutes for every day"), "{}", brief);
    assert!(brief.contains("120 crew-minutes (2 h)"), "{}", brief);
}
