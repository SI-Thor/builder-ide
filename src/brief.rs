//! Rendering the contract terms for a seat's BRIEF.md.
//!
//! The general contractor does not hand a subcontractor a blank check. This
//! is the block that says what the job is, when it is due, what it costs, and
//! where the sub has to stop and report.

use crate::model::{Job, State};

/// Render the contract block for a job.
pub fn brief_block(state: &State, job_id: &str) -> Result<String, String> {
    let job = state
        .job(job_id)
        .ok_or_else(|| format!("no such job: {}", job_id))?;
    let bid = job.awarded_bid(&state.bids);
    let sub = if job.awarded_sub.is_empty() {
        "(not awarded)".to_string()
    } else {
        job.awarded_sub.clone()
    };

    let mut out = String::new();
    out.push_str(&format!("## Contract: {} — {}\n\n", job.id, job.title));
    out.push_str(&format!(
        "You are the subcontractor on job {}. Job class: `{}`.\n\n",
        job.id, job.class
    ));

    out.push_str(&format!("**What was asked.** {}\n\n", job.scope));

    out.push_str(&format!(
        "**The goal line (acceptance test).** {}.\n",
        job.acceptance.describe()
    ));
    if !job.acceptance.note.is_empty() {
        out.push_str(&format!("_{}_\n", job.acceptance.note));
    }
    out.push('\n');

    out.push_str(&format!(
        "- **Job-time (T-minus):** {} from the award. Past that, the job is late and the penalty starts to run.\n",
        fmt_minutes(job.effective_deadline_min())
    ));
    out.push_str(&format!(
        "- **Crew-time ceiling (budget):** {}.\n",
        fmt_crew(job.effective_budget_min())
    ));
    out.push_str(&format!(
        "- **The general contractor's estimate for this job:** {}.\n",
        fmt_crew(job.estimate_min)
    ));

    if let Some(b) = bid {
        out.push_str(&format!(
            "- **Your bid:** {}, {} of job-time, confidence {:.2} ({}).\n",
            fmt_crew(b.crew_min.unwrap_or(0.0)),
            fmt_minutes(b.job_min.unwrap_or(0.0)),
            b.confidence,
            if b.computed {
                "computed from your track record"
            } else {
                "submitted by hand"
            }
        ));
        if !b.milestones.is_empty() {
            out.push_str("- **Milestones:**\n");
            for m in &b.milestones {
                out.push_str(&format!("  - {}\n", m));
            }
        }
    }

    let stop_at = job.effective_bid_min(bid) * job.stop_ratio;
    out.push_str(&format!(
        "- **Stop rule:** at {:.0}% of your bid crew-time ({}) with the goal line still not passing, STOP and report. No open-ended runs; the ledger refuses more burn until the general contractor re-scopes the job, extends it with a change order, or cancels it.\n",
        job.stop_ratio * 100.0,
        fmt_crew(stop_at)
    ));

    out.push_str(&format!(
        "- **Penalty:** {} for every day you are late. Crew-time spent past your bid becomes debt you carry; an underrun repays it.\n",
        fmt_crew(job.penalty_per_day_min)
    ));

    out.push_str(&format!(
        "- **Change orders:** if the general contractor extends the scope or the allowance, it records a change order in the ledger and your bid moves with it. Never change the scope without one.\n"
    ));

    out.push_str(&format!(
        "- **Ledger:** job {} in `ledger.jsonl`. Report your burn at every milestone with\n  `gc checkpoint --job {} --crew-used-min <minutes>`\n  and close with\n  `gc close --job {} --crew-min <minutes> --accepted`\n  once the goal line passes.\n",
        job.id, job.id, job.id
    ));

    if !job.change_orders.is_empty() {
        out.push_str("\n**Change orders on this job.**\n");
        for c in &job.change_orders {
            out.push_str(&format!(
                "- {} — {}, {} of job-time. {}\n",
                c.ts,
                fmt_crew(c.add_crew_min),
                fmt_minutes(c.add_job_min),
                c.reason
            ));
        }
    }

    out.push_str(&format!(
        "\n_Seated on {} at {}. Contract rendered from the ledger; if this block and the ledger disagree, the ledger is right._\n",
        sub, job.id
    ));

    Ok(out)
}

/// Minutes as a readable duration: "600 minutes (10 h)" when it is a whole
/// number of minutes, "95.5 minutes" when it is not.
pub fn fmt_minutes(min: f64) -> String {
    let m = min.max(0.0);
    if (m - m.round()).abs() < 0.05 {
        let whole = m.round() as i64;
        if whole % 60 == 0 && whole > 0 {
            format!("{} minutes ({} h)", whole, whole / 60)
        } else {
            format!("{} minutes", whole)
        }
    } else {
        format!("{:.1} minutes", m)
    }
}

/// Crew-time, in the unit the ledger uses: "120 crew-minutes (2 h)".
pub fn fmt_crew(min: f64) -> String {
    let m = min.max(0.0);
    if (m - m.round()).abs() < 0.05 {
        let whole = m.round() as i64;
        if whole % 60 == 0 && whole > 0 {
            format!("{} crew-minutes ({} h)", whole, whole / 60)
        } else {
            format!("{} crew-minutes", whole)
        }
    } else {
        format!("{:.1} crew-minutes", m)
    }
}

/// A one-line summary of a job, for listings.
pub fn job_line(state: &State, job: &Job) -> String {
    let bids = state.bids_for(&job.id).len();
    let mut line = format!(
        "{} [{}] {} — budget {}, deadline {}",
        job.id,
        job.status.as_str(),
        job.title,
        fmt_minutes(job.budget_min),
        fmt_minutes(job.deadline_min)
    );
    if job.reconstructed {
        line.push_str(" (reconstructed)");
    }
    if !job.awarded_sub.is_empty() {
        line.push_str(&format!(" → {} ({} bids)", job.awarded_sub, bids));
    }
    line
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn minutes_read_like_a_person_wrote_them() {
        assert_eq!(fmt_minutes(60.0), "60 minutes (1 h)");
        assert_eq!(fmt_minutes(90.0), "90 minutes");
        assert_eq!(fmt_minutes(12.5), "12.5 minutes");
        assert_eq!(fmt_crew(120.0), "120 crew-minutes (2 h)");
        assert_eq!(fmt_crew(45.0), "45 crew-minutes");
    }
}
