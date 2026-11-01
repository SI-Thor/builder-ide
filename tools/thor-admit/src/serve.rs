//! Shared model servers: a model loaded once per box, not once per seat.
//!
//! The 22:09 incident had two d1-2B llama-servers running at once because
//! two seats each started one. A model's memory cost is paid per *box*, not
//! per seat, so the registry's whole job is to make the second ask find the
//! first: `thor-admit serve d1-2B --port 8100 -- llama-server ...` returns
//! the port of a server that is already answering, and only starts a new
//! one when nobody is.
//!
//! The registry is a small JSON file beside the daemon's state
//! (`servers.json`), guarded by an flock, and its word is worth exactly as
//! much as the port probe that backs it: an entry whose port no longer
//! answers is not an entry. The daemon is not involved — a server runs
//! under an ordinary live lease, so admission, the watchdog and the
//! heartbeat all apply to it exactly as they do to any other work.

use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader};
use std::net::{IpAddr, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::clock;

/// How long to give a port probe. A server answering its port is the
/// registry's only definition of "served", so the probe is short: the
/// caller is a seat waiting to start work, not a health check.
const PROBE_TIMEOUT: Duration = Duration::from_millis(250);

/// One registered server.
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct ServerEntry {
    /// The model's name, as the seats ask for it (`d1-2B`).
    pub model: String,
    /// The port the server answers on.
    pub port: u16,
    /// When the entry was written, RFC 3339 UTC.
    pub at: String,
}

/// Is anything answering on this port, on the loopback the seats use?
pub fn port_answers(port: u16) -> bool {
    let address = SocketAddr::new(IpAddr::from([127, 0, 0, 1]), port);
    TcpStream::connect_timeout(&address, PROBE_TIMEOUT).is_ok()
}

/// The registry of running model servers.
#[derive(Debug)]
pub struct Registry {
    /// Where the entries are kept.
    path: PathBuf,
    /// The lock file that makes read-modify-write safe across seats.
    lock: PathBuf,
}

impl Registry {
    /// A registry kept in a daemon's state directory.
    pub fn new(state_dir: &Path) -> Registry {
        Registry {
            path: state_dir.join("servers.json"),
            lock: state_dir.join("servers.lock"),
        }
    }

    /// Where the entries are kept, for tests and for `status`.
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// The entries worth believing: those whose port still answers. An
    /// entry whose server died is not an entry, whatever the file says.
    pub fn live(&self) -> Vec<ServerEntry> {
        self.read()
            .into_iter()
            .filter(|entry| port_answers(entry.port))
            .collect()
    }

    /// The server for one model, if it is answering.
    pub fn find(&self, model: &str) -> Option<ServerEntry> {
        self.live().into_iter().find(|entry| entry.model == model)
    }

    /// Record an entry, replacing any this model already has.
    ///
    /// The whole read-modify-write sits under the registry's flock, so two
    /// seats recording at once cannot lose one another's entry.
    pub fn record(&self, entry: ServerEntry) {
        self.with_lock(|entries| {
            entries.retain(|other| other.model != entry.model);
            entries.push(entry);
        });
    }

    /// Drop this model's entry.
    pub fn remove(&self, model: &str) {
        self.with_lock(|entries| entries.retain(|other| other.model != model));
    }

    /// Read the entries as they are written. Unreadable is empty: a torn
    /// file must not take the registry's memory of a running server with it.
    fn read(&self) -> Vec<ServerEntry> {
        File::open(&self.path)
            .map(|file| {
                BufReader::new(file)
                    .lines()
                    .map_while(Result::ok)
                    .filter(|line| !line.trim().is_empty())
                    .filter_map(|line| serde_json::from_str(&line).ok())
                    .collect()
            })
            .unwrap_or_default()
    }

    /// Rewrite the entries under the registry's lock.
    fn with_lock(&self, edit: impl FnOnce(&mut Vec<ServerEntry>)) {
        use std::os::unix::io::AsRawFd;
        if let Some(parent) = self.path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let Ok(guard) = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(&self.lock)
        else {
            return;
        };
        let rc = unsafe { libc::flock(guard.as_raw_fd(), libc::LOCK_EX) };
        if rc != 0 {
            return;
        }
        let mut entries = self.read();
        edit(&mut entries);
        let text: String = entries
            .iter()
            .filter_map(|entry| serde_json::to_string(entry).ok())
            .collect::<Vec<_>>()
            .join("\n");
        let temporary = self.path.with_extension("tmp");
        if std::fs::write(&temporary, text + "\n").is_ok() {
            let _ = std::fs::rename(&temporary, &self.path);
        }
    }
}

/// A new entry for a server that has just answered its port.
pub fn entry(model: &str, port: u16) -> ServerEntry {
    ServerEntry {
        model: model.to_string(),
        port,
        at: clock::rfc3339_now(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "thor-admit-serve-{}-{name}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn a_free_port_is_not_answering() {
        // Bind a port, note it, let it go: nothing answers it now.
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        drop(listener);
        assert!(!port_answers(port));
    }

    #[test]
    fn an_answering_port_is_answering() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(port_answers(port));
    }

    #[test]
    fn an_entry_whose_port_died_is_not_live() {
        let dir = temp_dir("dead-entry");
        let registry = Registry::new(&dir);
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        registry.record(entry("d1-2B", port));
        assert!(registry.find("d1-2B").is_some(), "the live server is found");
        // The server goes away; the file still says it is there.
        drop(listener);
        assert!(
            registry.find("d1-2B").is_none(),
            "a dead server is still in the file: {:?}",
            std::fs::read_to_string(registry.path()).unwrap_or_default()
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn recording_twice_replaces_rather_than_doubles() {
        let dir = temp_dir("replace");
        let registry = Registry::new(&dir);
        registry.record(entry("d1-2B", 8100));
        registry.record(entry("d1-2B", 8101));
        registry.record(entry("qwen", 8200));
        let file = registry.read();
        assert_eq!(file.len(), 2, "one entry per model: {file:?}");
        assert!(file.iter().any(|entry| entry.model == "d1-2B" && entry.port == 8101));
        registry.remove("d1-2B");
        assert_eq!(registry.read().len(), 1, "the model's entry is gone");
        let _ = std::fs::remove_dir_all(&dir);
    }
}
