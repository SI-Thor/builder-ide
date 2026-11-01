//! The presence queue: work that is **registered**, and runs when the box has
//! room for it.
//!
//! The box is not idle because nobody asked it to be busy; it is idle
//! because the useful work was never registered. The presence queue is that
//! registration: a list of commands, each with a tier, an estimated peak and
//! a resumability flag.
//!
//! * A job runs **only when live work is not waiting**. The live queue has
//!   head-of-line blocking, so a live request that cannot be admitted blocks
//!   the presence queue behind it — the presence work must not make a live
//!   request's wait longer.
//! * A job is **pre-empted** when live work needs the memory the job holds,
//!   or when live work needs the GPU. A pre-empted job that is marked
//!   resumable goes back in the queue and runs again when there is room.
//! * A job is **never** started without a lease: the daemon holds the lease
//!   lock for it, exactly as a client would.
//!
//! The queue is a file (`<state-dir>/presence.json`), so it survives the
//! daemon and can be edited by hand; the daemon re-reads it when it changes.

use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::tier::Tier;

/// A registered job.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PresenceSpec {
    /// The daemon's number for this job.
    pub id: u64,
    /// The name the job is known by.
    pub label: String,
    /// Which tier it belongs to. `live` is not used here: a presence job is
    /// by definition work the box does when it has room.
    pub tier: Tier,
    /// The memory the job is expected to take. The daemon holds the lease to
    /// this number, so it is charged against the headroom like any lease.
    pub peak_bytes: u64,
    /// May this job be started again after it was pre-empted? A resumable job
    /// is one whose command can pick up where it left off (its own
    /// checkpoint); the daemon re-runs the same command.
    pub resumable: bool,
    /// The command to run.
    pub command: Vec<String>,
    /// Is the job wanted? A disabled job stays registered and does not run.
    #[serde(default = "default_true")]
    pub enabled: bool,
}

fn default_true() -> bool {
    true
}

impl PresenceSpec {
    /// A new job, as it is registered.
    pub fn new(
        id: u64,
        label: &str,
        tier: Tier,
        peak_bytes: u64,
        resumable: bool,
        command: Vec<String>,
    ) -> PresenceSpec {
        PresenceSpec {
            id,
            label: label.to_string(),
            tier,
            peak_bytes,
            resumable,
            command,
            enabled: true,
        }
    }
}

/// What a job is doing.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobState {
    /// Registered, waiting for room.
    Pending,
    /// Running.
    Running,
    /// Running, but stopped (the watchdog or a pre-emption froze it).
    Stopped,
    /// Stopped by live work. It will run again if it is resumable.
    Preempted,
    /// It finished, with exit code zero.
    Done,
    /// It stopped with an error.
    Failed,
}

impl JobState {
    pub fn as_str(&self) -> &'static str {
        match self {
            JobState::Pending => "pending",
            JobState::Running => "running",
            JobState::Stopped => "stopped",
            JobState::Preempted => "preempted",
            JobState::Done => "done",
            JobState::Failed => "failed",
        }
    }
}

/// One registered job, with what has happened to it.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct PresenceJob {
    pub spec: PresenceSpec,
    pub state: JobState,
    /// How many times it has been started.
    pub attempts: u32,
    /// The exit code of the last run, if it ran.
    pub last_exit: Option<i32>,
    /// How many times live work has pre-empted it.
    pub preemptions: u32,
}

impl PresenceJob {
    pub fn new(spec: PresenceSpec) -> PresenceJob {
        PresenceJob {
            spec,
            state: JobState::Pending,
            attempts: 0,
            last_exit: None,
            preemptions: 0,
        }
    }
}

/// The queue of registered jobs.
///
/// The order is the tier first (the most urgent tier first) and the
/// registration order inside a tier. So a preparation job runs before a
/// practice job, and a practice job runs before a study job.
#[derive(Debug)]
pub struct PresenceQueue {
    jobs: Vec<PresenceJob>,
    next_id: u64,
}

impl Default for PresenceQueue {
    fn default() -> PresenceQueue {
        // The ids start at one, like the lease ids: a job numbered zero
        // reads like "no job" in a log line.
        PresenceQueue {
            jobs: Vec::new(),
            next_id: 1,
        }
    }
}

impl PresenceQueue {
    pub fn new() -> PresenceQueue {
        PresenceQueue::default()
    }

    /// The jobs, in the order they run.
    pub fn jobs(&self) -> &[PresenceJob] {
        &self.jobs
    }

    /// The jobs, mutable.
    pub fn jobs_mut(&mut self) -> &mut Vec<PresenceJob> {
        &mut self.jobs
    }

    /// The next id a job will get.
    pub fn next_id(&self) -> u64 {
        self.next_id
    }

    /// Set the next id (used when a stored queue is read back).
    pub fn set_next_id(&mut self, next_id: u64) {
        self.next_id = next_id;
    }

    /// Register a job. The queue keeps its order: the tier decides where the
    /// job goes, and jobs of the same tier keep the order they arrived in.
    pub fn push(&mut self, job: PresenceJob) -> u64 {
        let id = job.spec.id;
        let tier = job.spec.tier;
        let position = self
            .jobs
            .iter()
            .position(|other| other.spec.tier > tier)
            .unwrap_or(self.jobs.len());
        self.jobs.insert(position, job);
        if id >= self.next_id {
            self.next_id = id + 1;
        }
        id
    }

    /// Take a job out of the queue.
    pub fn remove(&mut self, id: u64) -> Option<PresenceJob> {
        let index = self.jobs.iter().position(|job| job.spec.id == id)?;
        Some(self.jobs.remove(index))
    }

    /// One job, by id.
    pub fn get(&self, id: u64) -> Option<&PresenceJob> {
        self.jobs.iter().find(|job| job.spec.id == id)
    }

    /// One job, by id, mutably.
    pub fn get_mut(&mut self, id: u64) -> Option<&mut PresenceJob> {
        self.jobs.iter_mut().find(|job| job.spec.id == id)
    }

    /// The job that should run next: the most urgent tier that is pending and
    /// enabled. A job that is already running or finished is not a candidate.
    pub fn next_runnable(&self) -> Option<&PresenceJob> {
        self.jobs.iter().find(|job| {
            job.spec.enabled
                && matches!(job.state, JobState::Pending | JobState::Preempted)
        })
    }

    /// Every job that is registered and has not finished.
    pub fn outstanding(&self) -> usize {
        self.jobs
            .iter()
            .filter(|job| !matches!(job.state, JobState::Done | JobState::Failed))
            .count()
    }
}

/// The file the queue is kept in.
#[derive(Debug)]
pub struct PresenceStore {
    path: PathBuf,
}

/// What is in the store file.
#[derive(Clone, Debug, Default, Serialize, Deserialize)]
struct StoreFile {
    #[serde(default)]
    jobs: Vec<PresenceJob>,
    #[serde(default)]
    next_id: u64,
}

impl PresenceStore {
    pub fn new(path: &Path) -> PresenceStore {
        PresenceStore {
            path: path.to_path_buf(),
        }
    }

    /// The path of the store.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Read the queue back.
    ///
    /// A file that cannot be read is an empty queue, not a crash: the daemon
    /// must come up even if the file was truncated by a bad write.
    pub fn load(&self) -> PresenceQueue {
        let mut queue = PresenceQueue::new();
        let Ok(file) = File::open(&self.path) else {
            return queue;
        };
        for line in BufReader::new(file).lines().map_while(Result::ok) {
            if line.trim().is_empty() {
                continue;
            }
            let Ok(stored) = serde_json::from_str::<StoreFile>(&line) else {
                continue;
            };
            for job in stored.jobs {
                queue.push(job);
            }
            if stored.next_id > queue.next_id() {
                queue.set_next_id(stored.next_id);
            }
        }
        queue
    }

    /// Write the queue out.
    ///
    /// The file is written whole, through a temporary file and a rename, so a
    /// reader never sees half a queue.
    pub fn save(&self, queue: &PresenceQueue) -> std::io::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let stored = StoreFile {
            jobs: queue.jobs().to_vec(),
            next_id: queue.next_id(),
        };
        let mut text = serde_json::to_string(&stored).map_err(std::io::Error::other)?;
        text.push('\n');
        let temporary = self.path.with_extension("json.new");
        {
            let mut file = OpenOptions::new()
                .create(true)
                .write(true)
                .truncate(true)
                .open(&temporary)?;
            file.write_all(text.as_bytes())?;
            file.flush()?;
        }
        std::fs::rename(&temporary, &self.path)
    }
}

/// Start a command in its own process group.
///
/// The daemon runs presence jobs itself, so it needs the same thing the
/// client does: a child that can be signalled as a group, and that never
/// inherits the daemon's own descriptors.
pub fn spawn(command: &[String]) -> std::io::Result<(libc::pid_t, i32)> {
    if command.is_empty() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "there is no command to run",
        ));
    }
    let pid = unsafe { libc::fork() };
    if pid < 0 {
        return Err(std::io::Error::last_os_error());
    }
    if pid == 0 {
        unsafe {
            libc::setpgid(0, 0);
            exec_command(command);
        }
    }
    // Both sides set the group; whoever wins, it is the same group.
    unsafe { libc::setpgid(pid, pid) };
    Ok((pid, pid as i32))
}

/// `execvp` the command. Only called in the forked child; it never returns.
fn exec_command(command: &[String]) -> ! {
    let program = std::ffi::CString::new(command[0].clone()).unwrap_or_default();
    let argv: Vec<std::ffi::CString> = command
        .iter()
        .map(|part| std::ffi::CString::new(part.clone()).unwrap_or_default())
        .collect();
    let mut pointers: Vec<*const libc::c_char> = argv.iter().map(|part| part.as_ptr()).collect();
    pointers.push(std::ptr::null());
    unsafe { libc::execvp(program.as_ptr(), pointers.as_ptr()) };
    let message = format!(
        "thor-admit: cannot run {}: {}\n",
        command.first().map(String::as_str).unwrap_or(""),
        std::io::Error::last_os_error()
    );
    unsafe {
        libc::write(2, message.as_ptr() as *const libc::c_void, message.len());
        libc::_exit(127);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn job(id: u64, tier: Tier) -> PresenceJob {
        PresenceJob::new(PresenceSpec::new(
            id,
            &format!("job{id}"),
            tier,
            1024,
            true,
            vec!["true".to_string()],
        ))
    }

    #[test]
    fn the_most_urgent_tier_runs_first() {
        let mut queue = PresenceQueue::new();
        queue.push(job(1, Tier::Study));
        queue.push(job(2, Tier::Live));
        queue.push(job(3, Tier::Practice));
        queue.push(job(4, Tier::Preparation));
        let order: Vec<u64> = queue.jobs().iter().map(|j| j.spec.id).collect();
        assert_eq!(order, vec![2, 4, 3, 1]);
    }

    #[test]
    fn jobs_of_one_tier_keep_their_order() {
        let mut queue = PresenceQueue::new();
        queue.push(job(1, Tier::Study));
        queue.push(job(2, Tier::Study));
        queue.push(job(3, Tier::Preparation));
        let order: Vec<u64> = queue.jobs().iter().map(|j| j.spec.id).collect();
        assert_eq!(order, vec![3, 1, 2]);
    }

    #[test]
    fn the_next_runnable_job_is_the_first_pending_one() {
        let mut queue = PresenceQueue::new();
        queue.push(job(1, Tier::Study));
        let mut running = job(2, Tier::Preparation);
        running.state = JobState::Running;
        queue.push(running);
        queue.push(job(3, Tier::Practice));
        assert_eq!(queue.next_runnable().unwrap().spec.id, 3);
    }

    #[test]
    fn a_disabled_job_does_not_run() {
        let mut queue = PresenceQueue::new();
        let mut disabled = job(1, Tier::Study);
        disabled.spec.enabled = false;
        queue.push(disabled);
        assert!(queue.next_runnable().is_none());
    }

    #[test]
    fn a_finished_job_is_not_a_candidate() {
        let mut queue = PresenceQueue::new();
        let mut done = job(1, Tier::Study);
        done.state = JobState::Done;
        queue.push(done);
        assert!(queue.next_runnable().is_none());
        assert_eq!(queue.outstanding(), 0);
    }

    #[test]
    fn a_removed_job_is_gone() {
        let mut queue = PresenceQueue::new();
        queue.push(job(7, Tier::Study));
        assert!(queue.remove(7).is_some());
        assert!(queue.remove(7).is_none());
        assert!(queue.get(7).is_none());
    }

    #[test]
    fn the_queue_survives_a_round_trip_through_the_file() {
        let path = std::env::temp_dir().join(format!(
            "thor-admit-presence-{}-{}.json",
            std::process::id(),
            "roundtrip"
        ));
        let _ = std::fs::remove_file(&path);
        let store = PresenceStore::new(&path);
        let mut queue = PresenceQueue::new();
        queue.push(job(1, Tier::Study));
        queue.push(job(2, Tier::Preparation));
        store.save(&queue).unwrap();

        let back = store.load();
        assert_eq!(back.jobs().len(), 2);
        assert_eq!(back.jobs()[0].spec.id, 2, "the tier order survives");
        assert_eq!(back.next_id(), 3);
        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn a_store_that_is_not_there_is_an_empty_queue() {
        let path = std::env::temp_dir().join(format!(
            "thor-admit-presence-{}-missing.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        let queue = PresenceStore::new(&path).load();
        assert!(queue.jobs().is_empty());
    }

    #[test]
    fn a_torn_line_does_not_take_the_queue_with_it() {
        let path = std::env::temp_dir().join(format!(
            "thor-admit-presence-{}-torn.json",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&path);
        let store = PresenceStore::new(&path);
        let mut queue = PresenceQueue::new();
        queue.push(job(1, Tier::Study));
        store.save(&queue).unwrap();
        let mut text = std::fs::read_to_string(&path).unwrap();
        text.push_str("{\"jobs\": [{\"id\": 2, \"lab");
        std::fs::write(&path, text).unwrap();

        let back = store.load();
        assert_eq!(back.jobs().len(), 1, "the whole job survives");
        let _ = std::fs::remove_file(&path);
    }
}
