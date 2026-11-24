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

// ------------------------------------------- the bridge's machine contract --

/// A tiny JSON reader, just enough for the assertions below. gc prints
/// canonical JSON — one line, no spaces — so this stays small.
#[derive(Clone, Debug, PartialEq)]
enum J {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<J>),
    Obj(Vec<(String, J)>),
}

impl J {
    fn get(&self, key: &str) -> Option<&J> {
        match self {
            J::Obj(items) => items.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// A nested field: `at(&["check", "verdict"])`.
    fn at(&self, path: &[&str]) -> Option<&J> {
        let mut cur = self;
        for key in path {
            cur = cur.get(key)?;
        }
        Some(cur)
    }

    fn as_str(&self) -> Option<&str> {
        match self {
            J::Str(s) => Some(s.as_str()),
            _ => None,
        }
    }

    fn as_f64(&self) -> Option<f64> {
        match self {
            J::Num(n) => Some(*n),
            _ => None,
        }
    }

    fn as_bool(&self) -> Option<bool> {
        match self {
            J::Bool(b) => Some(*b),
            _ => None,
        }
    }

    fn as_arr(&self) -> Option<&Vec<J>> {
        match self {
            J::Arr(a) => Some(a),
            _ => None,
        }
    }
}

fn parse_json(text: &str) -> Result<J, String> {
    let b = text.as_bytes();
    let mut i = 0usize;
    let v = json_value(b, &mut i)?;
    json_skip_ws(b, &mut i);
    if i != b.len() {
        return Err(format!("trailing text at byte {}", i));
    }
    Ok(v)
}

fn json_skip_ws(b: &[u8], i: &mut usize) {
    while *i < b.len() && (b[*i] as char).is_ascii_whitespace() {
        *i += 1;
    }
}

fn json_value(b: &[u8], i: &mut usize) -> Result<J, String> {
    json_skip_ws(b, i);
    match b.get(*i) {
        None => Err("unexpected end of input".to_string()),
        Some(b'{') => json_object(b, i),
        Some(b'[') => json_array(b, i),
        Some(b'"') => Ok(J::Str(json_string(b, i)?)),
        Some(b't') => {
            json_expect(b, i, "true")?;
            Ok(J::Bool(true))
        }
        Some(b'f') => {
            json_expect(b, i, "false")?;
            Ok(J::Bool(false))
        }
        Some(b'n') => {
            json_expect(b, i, "null")?;
            Ok(J::Null)
        }
        Some(_) => json_number(b, i),
    }
}

fn json_expect(b: &[u8], i: &mut usize, word: &str) -> Result<(), String> {
    if b[*i..].starts_with(word.as_bytes()) {
        *i += word.len();
        Ok(())
    } else {
        Err(format!("expected '{}' at byte {}", word, i))
    }
}

fn json_object(b: &[u8], i: &mut usize) -> Result<J, String> {
    *i += 1; // '{'
    let mut items: Vec<(String, J)> = Vec::new();
    json_skip_ws(b, i);
    if b.get(*i) == Some(&b'}') {
        *i += 1;
        return Ok(J::Obj(items));
    }
    loop {
        json_skip_ws(b, i);
        let key = json_string(b, i)?;
        json_skip_ws(b, i);
        if b.get(*i) != Some(&b':') {
            return Err(format!("expected ':' at byte {}", i));
        }
        *i += 1;
        let val = json_value(b, i)?;
        items.push((key, val));
        json_skip_ws(b, i);
        match b.get(*i) {
            Some(b',') => *i += 1,
            Some(b'}') => {
                *i += 1;
                return Ok(J::Obj(items));
            }
            _ => return Err(format!("expected ',' or '}}' at byte {}", i)),
        }
    }
}

fn json_array(b: &[u8], i: &mut usize) -> Result<J, String> {
    *i += 1; // '['
    let mut items: Vec<J> = Vec::new();
    json_skip_ws(b, i);
    if b.get(*i) == Some(&b']') {
        *i += 1;
        return Ok(J::Arr(items));
    }
    loop {
        let val = json_value(b, i)?;
        items.push(val);
        json_skip_ws(b, i);
        match b.get(*i) {
            Some(b',') => *i += 1,
            Some(b']') => {
                *i += 1;
                return Ok(J::Arr(items));
            }
            _ => return Err(format!("expected ',' or ']' at byte {}", i)),
        }
    }
}

fn json_string(b: &[u8], i: &mut usize) -> Result<String, String> {
    if b.get(*i) != Some(&b'"') {
        return Err(format!("expected a string at byte {}", i));
    }
    *i += 1;
    let mut out = String::new();
    loop {
        let c = match b.get(*i) {
            Some(c) => *c,
            None => return Err("unterminated string".to_string()),
        };
        *i += 1;
        match c {
            b'"' => return Ok(out),
            b'\\' => {
                let e = match b.get(*i) {
                    Some(e) => *e,
                    None => return Err("unterminated escape".to_string()),
                };
                *i += 1;
                match e {
                    b'"' => out.push('"'),
                    b'\\' => out.push('\\'),
                    b'/' => out.push('/'),
                    b'b' => out.push('\u{08}'),
                    b'f' => out.push('\u{0c}'),
                    b'n' => out.push('\n'),
                    b'r' => out.push('\r'),
                    b't' => out.push('\t'),
                    b'u' => {
                        let hex = std::str::from_utf8(&b[*i..*i + 4])
                            .map_err(|_| "bad \\u escape".to_string())?;
                        let cp = u32::from_str_radix(hex, 16)
                            .map_err(|_| "bad \\u escape".to_string())?;
                        *i += 4;
                        out.push(char::from_u32(cp).unwrap_or('\u{fffd}'));
                    }
                    _ => return Err(format!("bad escape at byte {}", i)),
                }
            }
            _ => {
                // Collect the UTF-8 sequence.
                let start = *i - 1;
                let len = if c < 0x80 {
                    1
                } else if c >> 5 == 0b110 {
                    2
                } else if c >> 4 == 0b1110 {
                    3
                } else {
                    4
                };
                *i = start + len;
                out.push_str(
                    std::str::from_utf8(&b[start..*i]).map_err(|_| "bad utf-8".to_string())?,
                );
            }
        }
    }
}

fn json_number(b: &[u8], i: &mut usize) -> Result<J, String> {
    let start = *i;
    while let Some(c) = b.get(*i) {
        if c.is_ascii_digit() || matches!(c, b'.' | b'e' | b'E' | b'-' | b'+') {
            *i += 1;
        } else {
            break;
        }
    }
    let s = std::str::from_utf8(&b[start..*i]).map_err(|_| "bad number".to_string())?;
    s.parse::<f64>()
        .map(J::Num)
        .map_err(|_| format!("bad number '{}'", s))
}

/// The JSON line gc printed last — the row body it wrote.
fn json_line(out: &str) -> J {
    let line = out
        .lines()
        .filter(|l| l.trim_start().starts_with('{'))
        .last()
        .expect("no JSON line on stdout");
    parse_json(line.trim())
        .unwrap_or_else(|e| panic!("the JSON line does not parse ({}): {}", e, line))
}

#[test]
fn the_external_id_is_stored_in_the_job_row() {
    let dir = workdir("external-id");

    ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--external-id", "WO-42", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let row = ledger_row_of(&dir, "job.new");
    assert!(
        row.contains("\"external_id\":\"WO-42\""),
        "the job row must carry the caller's own id:\n{}",
        row
    );

    // A job nobody keyed is keyed by nothing: the field is there, empty.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t2", "--class", "build-feature", "--scope", "s",
            "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let row = ledger_row_of(&dir, "job.new");
    assert!(
        row.contains("\"external_id\":\"\""),
        "an unkeyed job still has the field, empty:\n{}",
        row
    );
}

#[test]
fn the_json_flag_prints_the_row_body_of_every_writing_command() {
    let dir = workdir("json-flag");

    // The job: the row body, with the ids and the numbers.
    let out = ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
            "--external-id", "WO-7", "--json",
        ],
    );
    let job = json_line(&out);
    assert_eq!(job.get("id").and_then(|v| v.as_str()), Some("J001"));
    assert_eq!(job.get("external_id").and_then(|v| v.as_str()), Some("WO-7"));
    assert_eq!(job.get("title").and_then(|v| v.as_str()), Some("t"));
    assert_eq!(job.get("scope").and_then(|v| v.as_str()), Some("s"));
    assert_eq!(job.get("class").and_then(|v| v.as_str()), Some("build-feature"));
    assert_eq!(
        job.at(&["acceptance", "kind"]).and_then(|v| v.as_str()),
        Some("cmd")
    );
    assert_eq!(job.get("deadline_min").and_then(|v| v.as_f64()), Some(1440.0));
    assert_eq!(job.get("estimate_min").and_then(|v| v.as_f64()), Some(60.0));
    assert_eq!(job.get("budget_min").and_then(|v| v.as_f64()), Some(90.0));
    assert_eq!(job.get("stop_ratio").and_then(|v| v.as_f64()), Some(0.8));
    assert!(job.get("clauses").and_then(|v| v.as_arr()).is_some());

    // The bid.
    let out = ok(
        &dir,
        &[
            "bid", "--job", "J001", "--sub", "zcode", "--crew-min", "60", "--submit", "--json",
        ],
    );
    let bid = json_line(&out);
    assert_eq!(bid.get("id").and_then(|v| v.as_str()), Some("B001"));
    assert_eq!(bid.get("job_id").and_then(|v| v.as_str()), Some("J001"));
    assert_eq!(bid.get("sub").and_then(|v| v.as_str()), Some("zcode"));
    assert_eq!(bid.get("crew_min").and_then(|v| v.as_f64()), Some(60.0));
    assert_eq!(bid.get("job_min").and_then(|v| v.as_f64()), Some(60.0));
    assert_eq!(bid.get("confidence").and_then(|v| v.as_f64()), Some(0.5));
    assert_eq!(bid.get("computed").and_then(|v| v.as_bool()), Some(false));
    assert!(bid.get("basis").and_then(|v| v.as_str()).is_some());

    // The award.
    let out = ok(&dir, &["award", "--job", "J001", "--bid", "B001", "--json"]);
    let award = json_line(&out);
    assert_eq!(award.get("job_id").and_then(|v| v.as_str()), Some("J001"));
    assert_eq!(award.get("bid_id").and_then(|v| v.as_str()), Some("B001"));
    assert_eq!(award.get("sub").and_then(|v| v.as_str()), Some("zcode"));
    assert!(award.get("score").and_then(|v| v.as_f64()).is_some());

    // The checkpoint: the burn, the stop demand and the check.
    let out = ok(
        &dir,
        &["checkpoint", "--job", "J001", "--crew-used-min", "30", "--json"],
    );
    let cp = json_line(&out);
    assert_eq!(cp.get("job_id").and_then(|v| v.as_str()), Some("J001"));
    assert_eq!(cp.get("crew_used_min").and_then(|v| v.as_f64()), Some(30.0));
    assert_eq!(cp.get("burn").and_then(|v| v.as_f64()), Some(0.5));
    assert_eq!(cp.get("stop_required").and_then(|v| v.as_bool()), Some(false));
    assert_eq!(
        cp.at(&["check", "verdict"]).and_then(|v| v.as_str()),
        Some("pass")
    );
    assert!(cp.get("metrics").and_then(|v| v.as_arr()).is_some());
    assert!(cp.get("clauses").and_then(|v| v.as_arr()).is_some());
    assert_eq!(
        cp.at(&["forecast", "verdict"]).and_then(|v| v.as_str()),
        Some("inconclusive")
    );

    // The close: the money and the verdict.
    let out = ok(&dir, &["close", "--job", "J001", "--crew-min", "50", "--json"]);
    let close = json_line(&out);
    assert_eq!(close.get("job_id").and_then(|v| v.as_str()), Some("J001"));
    assert_eq!(close.get("accepted").and_then(|v| v.as_bool()), Some(true));
    assert_eq!(
        close.get("acceptance_verdict").and_then(|v| v.as_str()),
        Some("pass")
    );
    assert_eq!(close.get("actual_crew_min").and_then(|v| v.as_f64()), Some(50.0));
    assert_eq!(close.get("actual_job_min").and_then(|v| v.as_f64()), Some(50.0));
    assert_eq!(close.get("late_days").and_then(|v| v.as_f64()), Some(0.0));
    assert_eq!(
        close.get("effective_bid_min").and_then(|v| v.as_f64()),
        Some(60.0)
    );
    assert_eq!(close.get("overrun_min").and_then(|v| v.as_f64()), Some(0.0));
    assert_eq!(close.get("penalty_min").and_then(|v| v.as_f64()), Some(0.0));
    assert_eq!(close.get("debt_delta_min").and_then(|v| v.as_f64()), Some(0.0));
    assert_eq!(close.get("method").and_then(|v| v.as_str()), Some("wall"));
    assert_eq!(
        close.at(&["check", "verdict"]).and_then(|v| v.as_str()),
        Some("pass")
    );
}

#[test]
fn the_json_line_is_added_after_the_human_lines() {
    let dir = workdir("json-last");
    let out = ok(
        &dir,
        &[
            "job", "new", "--title", "t", "--class", "build-feature", "--scope", "s",
            "--estimate-min", "60", "--deadline-min", "1440", "--json",
        ],
    );
    let lines: Vec<&str> = out.lines().filter(|l| !l.trim().is_empty()).collect();
    let last = lines.last().expect("no output");
    assert!(
        last.starts_with('{') && parse_json(last).is_ok(),
        "the JSON line must come last on stdout:\n{}",
        out
    );
    // The prose is still there: --json adds a line, it does not replace them.
    assert!(out.contains("row 0 written"), "{}", out);
    assert!(out.contains("goal line"), "{}", out);
}

#[test]
fn a_report_kind_close_can_say_it_could_not_be_judged() {
    let dir = workdir("close-inconclusive");

    // A job with no machine-checkable goal line: the desk's word is the check.
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

    // Nothing to say yet: the close must be told the outcome.
    let err = fails(&dir, &["close", "--job", &job, "--crew-min", "50"]);
    assert!(err.contains("state the outcome"), "{}", err);

    // "I could not tell" is a verdict of its own — not a failure.
    let out = ok(
        &dir,
        &["close", "--job", &job, "--crew-min", "50", "--check", "inconclusive", "--json"],
    );
    let close = json_line(&out);
    assert_eq!(
        close.get("acceptance_verdict").and_then(|v| v.as_str()),
        Some("inconclusive")
    );
    assert_eq!(close.get("accepted").and_then(|v| v.as_bool()), Some(false));
    assert_eq!(
        close.at(&["check", "verdict"]).and_then(|v| v.as_str()),
        Some("inconclusive")
    );

    // The desk's word still closes a job.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t2", "--class", "research-read", "--scope", "s",
            "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let job2 = last_job(&dir);
    ok(&dir, &["bid", "--job", &job2, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &job2, "--bid", &bid_id_of(&dir, &job2)]);
    let out = ok(
        &dir,
        &["close", "--job", &job2, "--crew-min", "50", "--accepted", "--json"],
    );
    let close = json_line(&out);
    assert_eq!(
        close.get("acceptance_verdict").and_then(|v| v.as_str()),
        Some("pass")
    );
    assert_eq!(close.get("accepted").and_then(|v| v.as_bool()), Some(true));

    // A machine-checkable goal line still refuses a stated outcome.
    ok(
        &dir,
        &[
            "job", "new", "--title", "t3", "--class", "research-read", "--scope", "s",
            "--accept-cmd", "true", "--estimate-min", "60", "--deadline-min", "1440",
        ],
    );
    let job3 = last_job(&dir);
    ok(&dir, &["bid", "--job", &job3, "--sub", "zcode", "--crew-min", "60", "--submit"]);
    ok(&dir, &["award", "--job", &job3, "--bid", &bid_id_of(&dir, &job3)]);
    let err = fails(&dir, &["close", "--job", &job3, "--crew-min", "50", "--check", "pass"]);
    assert!(err.contains("decides for itself"), "{}", err);
    let err = fails(&dir, &["close", "--job", &job3, "--crew-min", "50", "--accepted"]);
    assert!(err.contains("report-kind jobs only"), "{}", err);
}
