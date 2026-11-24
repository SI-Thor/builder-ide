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
        .env("GC_NOW", "1793640000") // 2026-11-02T17:20:00Z: a fixed clock
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
/// test controls the track record exactly. An accepted job gets a passing
/// acceptance command and a failing one a failing command — the verdict at
/// close comes from the command, never from a flag.
fn finished_job(dir: &Path, class: &str, sub: &str, bid_min: f64, actual_min: f64, accepted: bool) {
    let estimate = 100.0;
    ok(
        dir,
        &[
            "job", "new", "--title", "t", "--class", class, "--scope", "s",
            "--accept-cmd", if accepted { "true" } else { "false" },
            "--estimate-min", "100", "--deadline-min", "1440",
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
    ok(dir, &["close", "--job", &job_id, "--crew-min", actual.as_str()]);
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
    // against a 1440-minute deadline: one day late. The goal line (`true`)
    // is re-run by gc at close and passes.
    let closed = ok(
        &dir,
        &[
            "close", "--job", &job, "--crew-min", "90", "--job-min", "2880",
        ],
    );
    assert!(closed.contains("overrun 30"), "{}", closed);
    assert!(closed.contains("penalty 30"), "{}", closed);
    assert!(closed.contains("debt +60"), "{}", closed);
    assert!(closed.contains("goal line: pass"), "{}", closed);

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
        &["close", "--job", &job2, "--crew-min", "40"],
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
    // The goal line is a command that has not passed yet, so the stop rule
    // is in play: at 80% of the bid the check still fails.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "false", "--estimate-min", "100", "--deadline-min", "1440",
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

    // The promise moved with the change order: 100 + 60 = 160. The goal
    // line still fails at close (the command is `false`), and the close
    // says so honestly instead of taking a flag's word.
    let closed = ok(&dir, &["close", "--job", &job, "--crew-min", "120"]);
    assert!(closed.contains("against a promise of 160"), "{}", closed);
    assert!(closed.contains("goal line: fail"), "{}", closed);
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
        ok(&dir, &["close", "--job", &job, "--crew-min", "150"]);
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
        ok(&dir, &["close", "--job", &job, "--crew-min", "90"]);

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

// ------------------------------------------------------------- v2: checks --

#[test]
fn an_honest_close_reruns_the_acceptance_command() {
    let dir = workdir("honest");

    // A job whose goal line passes: the close needs no flag, the command
    // decides.
    ok(
        &dir,
        &[
            "job", "new", "--title", "good", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let good = last_job(&dir);
    ok(&dir, &["bid", "--job", &good, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &good, "--bid", &bid_id_of(&dir, &good)]);
    let closed = ok(&dir, &["close", "--job", &good, "--crew-min", "50"]);
    assert!(closed.contains("goal line: pass"), "{}", closed);
    assert!(closed.contains("exit 0"), "{}", closed);

    // A job whose goal line does not pass: same close, different verdict,
    // and no credit.
    ok(
        &dir,
        &[
            "job", "new", "--title", "bad", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "exit 7", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let bad = last_job(&dir);
    ok(&dir, &["bid", "--job", &bad, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &bad, "--bid", &bid_id_of(&dir, &bad)]);
    let closed_bad = ok(&dir, &["close", "--job", &bad, "--crew-min", "50"]);
    assert!(closed_bad.contains("goal line: fail"), "{}", closed_bad);
    assert!(closed_bad.contains("exit 7"), "{}", closed_bad);
    assert!(closed_bad.contains("did not pass"), "{}", closed_bad);

    // A flag cannot assert what a command decides — at close or at a
    // checkpoint.
    ok(
        &dir,
        &[
            "job", "new", "--title", "claimed", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "false", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let claimed = last_job(&dir);
    ok(&dir, &["bid", "--job", &claimed, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &claimed, "--bid", &bid_id_of(&dir, &claimed)]);

    let err = fails(&dir, &["close", "--job", &claimed, "--crew-min", "50", "--accepted"]);
    assert!(err.contains("report-kind jobs only"), "{}", err);

    let err = fails(
        &dir,
        &["checkpoint", "--job", &claimed, "--crew-used-min", "10", "--check", "pass"],
    );
    assert!(err.contains("decides for itself"), "{}", err);

    // A check that could not run says so, as inconclusive.
    let cp = ok(
        &dir,
        &[
            "checkpoint", "--job", &claimed, "--crew-used-min", "10",
            "--check", "inconclusive",
        ],
    );
    assert!(cp.contains("goal line: inconclusive"), "{}", cp);
}

#[test]
fn a_report_kind_job_closes_on_a_humans_word() {
    let dir = workdir("report-kind");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "research-read", "--scope", "s",
            "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let job = last_job(&dir);
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &job, "--bid", &bid_id_of(&dir, &job)]);

    // No machine check was written down, so the desk's word is the check —
    // but it must be given, not assumed.
    let err = fails(&dir, &["close", "--job", &job, "--crew-min", "50"]);
    assert!(err.contains("state the outcome"), "{}", err);

    let closed = ok(&dir, &["close", "--job", &job, "--crew-min", "50", "--accepted"]);
    assert!(closed.contains("goal line: pass"), "{}", closed);
    assert!(closed.contains("a human's judgement"), "{}", closed);
}

#[test]
fn actuals_below_the_last_checkpoint_are_refused() {
    let dir = workdir("floor");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
        ],
    );
    let job = last_job(&dir);
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "100", "--submit"]);
    ok(&dir, &["award", "--job", &job, "--bid", &bid_id_of(&dir, &job)]);
    ok(&dir, &["checkpoint", "--job", &job, "--crew-used-min", "50"]);

    // The ledger already holds a checkpoint at 50 crew-minutes: the close
    // cannot report less than what it measured.
    let err = fails(&dir, &["close", "--job", &job, "--crew-min", "40"]);
    assert!(err.contains("already reported"), "{}", err);

    ok(&dir, &["close", "--job", &job, "--crew-min", "55"]);
}

// ------------------------------------------------------------ v2: clauses --

#[test]
fn clauses_are_checked_and_penalized_at_close() {
    let dir = workdir("clauses");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
            "--clause", "coverage >= 0.8 penalty 30",
        ],
    );
    let job = last_job(&dir);
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "100", "--submit"]);
    // The award tightens the coverage clause: same metric, new terms.
    ok(
        &dir,
        &[
            "award", "--job", &job, "--bid", &bid_id_of(&dir, &job),
            "--clause", "coverage >= 0.9 penalty 45",
        ],
    );

    let cp = ok(
        &dir,
        &[
            "checkpoint", "--job", &job, "--crew-used-min", "20",
            "--metric", "coverage=0.85",
        ],
    );
    // The job's own clause (0.8) would pass 0.85; the negotiated one (0.9)
    // is the one in force.
    assert!(cp.contains("clause coverage: fail"), "{}", cp);

    let brief = ok(&dir, &["brief", "--job", &job]);
    assert!(brief.contains("coverage >= 0.9"), "{}", brief);
    assert!(brief.contains("negotiated at award"), "{}", brief);

    let closed = ok(
        &dir,
        &["close", "--job", &job, "--crew-min", "30", "--metric", "coverage=0.85"],
    );
    assert!(closed.contains("clause coverage breached"), "{}", closed);
    assert!(closed.contains("penalty 45"), "{}", closed);
    assert!(closed.contains("debt +45"), "{}", closed);
}

#[test]
fn a_clause_passing_costs_nothing_and_a_window_expires() {
    let dir = workdir("clause-window");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
            "--clause", "coverage >= 0.8 window 60 penalty 30",
        ],
    );
    let job = last_job(&dir);
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "100", "--submit"]);
    ok(
        &dir,
        &[
            "award", "--job", &job, "--bid", &bid_id_of(&dir, &job),
            "--at", "2026-11-02T11:00:00Z",
        ],
    );

    // Inside the window, a breach is a breach.
    let cp = ok(
        &dir,
        &[
            "checkpoint", "--job", &job, "--crew-used-min", "20",
            "--metric", "coverage=0.5", "--at", "2026-11-02T11:10:00Z",
        ],
    );
    assert!(cp.contains("clause coverage: fail"), "{}", cp);

    // Outside the window the clause is not in force: closing late with the
    // same breached metric costs nothing.
    let closed = ok(
        &dir,
        &[
            "close", "--job", &job, "--crew-min", "40",
            "--metric", "coverage=0.5", "--at", "2026-11-02T13:00:00Z",
        ],
    );
    assert!(closed.contains("penalty 0"), "{}", closed);
    assert!(closed.contains("debt +0"), "{}", closed);

    // And a clause that passes at close costs nothing either.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t2", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "1440",
            "--clause", "coverage >= 0.8 penalty 30",
        ],
    );
    let job2 = last_job(&dir);
    ok(&dir, &["bid", "--job", &job2, "--sub", "zcode", "--crew-min", "100", "--submit"]);
    ok(&dir, &["award", "--job", &job2, "--bid", &bid_id_of(&dir, &job2)]);
    let closed2 = ok(
        &dir,
        &["close", "--job", &job2, "--crew-min", "40", "--metric", "coverage=0.95"],
    );
    assert!(closed2.contains("penalty 0"), "{}", closed2);
}

// ----------------------------------------------------------- v2: forecast --

#[test]
fn the_forecast_warns_before_the_stop_line() {
    let dir = workdir("forecast");
    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "120",
        ],
    );
    let job = last_job(&dir);
    ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "100", "--submit"]);
    ok(
        &dir,
        &["award", "--job", &job, "--bid", &bid_id_of(&dir, &job), "--at", "2026-11-02T11:00:00Z"],
    );

    // 40 crew-min in 30 job-min: only 40% of the bid is spent, but at this
    // rate the 80% stop line is crossed well before the 120-minute
    // deadline — the warning fires now, not at the line.
    let cp = ok(
        &dir,
        &[
            "checkpoint", "--job", &job, "--crew-used-min", "40",
            "--at", "2026-11-02T11:30:00Z",
        ],
    );
    assert!(cp.contains("FORECAST WARNING"), "{}", cp);
    assert!(!cp.contains("STOP REQUIRED"), "{}", cp);

    let row = ledger_row_of(&dir, "checkpoint");
    assert!(row.contains("\"verdict\":\"warn\""), "{}", row);

    // A slow start forecasts under the line: no warning.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t2", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "100", "--deadline-min", "120",
        ],
    );
    let job2 = last_job(&dir);
    ok(&dir, &["bid", "--job", &job2, "--sub", "mcode", "--crew-min", "100", "--submit"]);
    ok(
        &dir,
        &["award", "--job", &job2, "--bid", &bid_id_of(&dir, &job2), "--at", "2026-11-02T11:00:00Z"],
    );
    let cp2 = ok(
        &dir,
        &[
            "checkpoint", "--job", &job2, "--crew-used-min", "10",
            "--at", "2026-11-02T11:30:00Z",
        ],
    );
    assert!(cp2.contains("under the stop line"), "{}", cp2);
    assert!(!cp2.contains("FORECAST WARNING"), "{}", cp2);
}

// ------------------------------------------------- v2: metric acceptance ----

#[test]
fn a_metric_goal_line_takes_a_value() {
    let dir = workdir("metric-acceptance");

    let make = |title: &str| {
        ok(
            &dir,
            &[
                "job", "new", "--title", title, "--class", "build-feature", "--scope", "s",
                "--accept-metric", "lines_covered", "--accept-at", "100",
                "--estimate-min", "60", "--deadline-min", "1440",
            ],
        );
        let job = last_job(&dir);
        ok(&dir, &["bid", "--job", &job, "--sub", "zcode", "--crew-min", "60", "--submit"]);
        ok(&dir, &["award", "--job", &job, "--bid", &bid_id_of(&dir, &job)]);
        job
    };

    // Over the threshold at close: pass, on the reported value.
    let over = make("over");
    let closed = ok(
        &dir,
        &["close", "--job", &over, "--crew-min", "50", "--metric", "lines_covered=120"],
    );
    assert!(closed.contains("goal line: pass"), "{}", closed);

    // Under the threshold: fail, honestly.
    let under = make("under");
    let closed_under = ok(
        &dir,
        &["close", "--job", &under, "--crew-min", "50", "--metric", "lines_covered=80"],
    );
    assert!(closed_under.contains("goal line: fail"), "{}", closed_under);

    // No value reported: the check could not run — inconclusive, not a
    // miss, and no credit either.
    let silent = make("silent");
    let closed_silent = ok(&dir, &["close", "--job", &silent, "--crew-min", "50"]);
    assert!(closed_silent.contains("goal line: inconclusive"), "{}", closed_silent);
    assert!(closed_silent.contains("the metric was not reported"), "{}", closed_silent);

    // At a checkpoint the metric is checked too, with the same honesty.
    let checked = make("checked");
    let cp = ok(
        &dir,
        &[
            "checkpoint", "--job", &checked, "--crew-used-min", "10",
            "--metric", "lines_covered=40",
        ],
    );
    assert!(cp.contains("goal line: fail"), "{}", cp);
}

#[test]
fn an_inconclusive_close_is_not_a_missed_goal_line() {
    let dir = workdir("inconclusive");

    // One job that failed its goal line, one that could not say: the report
    // must not read them the same.
    ok(
        &dir,
        &[
            "job", "new", "--title", "failed", "--class", "research-read", "--scope", "s",
            "--accept-cmd", "false", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let failed = last_job(&dir);
    ok(&dir, &["bid", "--job", &failed, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &failed, "--bid", &bid_id_of(&dir, &failed)]);
    ok(&dir, &["close", "--job", &failed, "--crew-min", "50"]);

    ok(
        &dir,
        &[
            "job", "new", "--title", "unsayable", "--class", "research-read", "--scope", "s",
            "--accept-metric", "pages_read", "--accept-at", "10",
            "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let unsayable = last_job(&dir);
    ok(&dir, &["bid", "--job", &unsayable, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &unsayable, "--bid", &bid_id_of(&dir, &unsayable)]);
    ok(&dir, &["close", "--job", &unsayable, "--crew-min", "50"]);

    let report = ok(&dir, &["report"]);
    assert!(report.contains("closed inconclusive 1"), "{}", report);

    let json = ok(&dir, &["report", "--json"]);
    assert!(json.contains("\"goal_line_inconclusive\":1"), "{}", json);
}

// ------------------------------------------------------------- helpers -----

fn last_job(dir: &Path) -> String {
    ok(dir, &["job", "list"])
        .lines()
        .last()
        .and_then(|l| l.split_whitespace().next())
        .expect("no job id")
        .to_string()
}

fn ledger_row_of(dir: &Path, kind: &str) -> String {
    let ledger = std::fs::read_to_string(dir.join("ledger.jsonl")).expect("no ledger");
    for line in ledger.lines().rev() {
        if line.contains(&format!("\"kind\":\"{}\"", kind)) {
            return line.to_string();
        }
    }
    panic!("no {} row", kind);
}
