//! Shared model servers: a model loaded once per box, not once per seat.
//!
//! The 22:09 incident had two d1-2B llama-servers running at once because
//! two seats each started one. A model's memory cost is paid per *box*, not
//! per seat, so the registry's whole job is to make the second ask find the
//! first: `thor-admit serve d1-2B --port 8100 -- llama-server ...` returns
//! the port of a server that is already answering, and only starts a new
//! one when nobody is.
//!
//! **What "the same model" means** (2026-11-01, 01:19: three d1-2B servers
//! ran at once as `d1-2B`, `d1-2B-baseline` and `d1-2B-batch`, because the
//! registry deduped by the *name* a seat happened to type). The registry is
//! keyed on what actually costs the memory and what actually changes the
//! serving: the **model file** (its path and a hash of its contents) plus a
//! **config tuple** (the command with the model file and the port taken
//! out). A seat that renames the model gets the running server; a seat
//! whose flags really differ — a bigger context, a different build — asks
//! for a variant, and a variant is its own server, because it is one.
//!
//! The registry is a small JSON file beside the daemon's state
//! (`servers.json`), guarded by an flock, and its word is worth exactly as
//! much as the port probe that backs it: an entry whose port no longer
//! answers is not an entry. The daemon is not involved — a server runs
//! under an ordinary live lease, so admission, the watchdog and the
//! heartbeat all apply to it exactly as they do to any other work.

use std::fs::{File, OpenOptions};
use std::io::{BufRead, BufReader, Read};
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
    /// What the entry is keyed on: the model file (path + content hash)
    /// and the config tuple. Two asks with the same key are asking for the
    /// same loaded model under the same flags, whatever names they typed.
    #[serde(default)]
    pub key: String,
    /// The model's name, as the first seat to start it asked for it
    /// (`d1-2B`). A display name, not the key.
    pub model: String,
    /// The port the server answers on.
    pub port: u16,
    /// The model file the server loaded, when the command named one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_file: Option<String>,
    /// A hash of the model file's contents, when the command named one.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model_hash: Option<String>,
    /// The config tuple: the command with the model file and the port taken
    /// out. Same file, same flags, same server.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub config: Option<String>,
    /// When the entry was written, RFC 3339 UTC.
    pub at: String,
}

/// What identifies the server a `serve` command would start.
#[derive(Clone, Debug, PartialEq)]
pub struct ServeKey {
    /// The registry key: what the entry is found by.
    pub key: String,
    /// The model file, when the command named one that exists.
    pub model_file: Option<PathBuf>,
    /// The hash of the model file's contents.
    pub model_hash: Option<String>,
    /// The config tuple: the command minus the model file and the port.
    pub config: String,
    /// Did the key come from a model file (`file`) or from falling back to
    /// the command alone (`name`)? A command with no model file in it can
    /// still be deduped, just on weaker grounds.
    pub basis: &'static str,
}

/// Work out what identifies the server this command would start.
///
/// The model file is found where the common servers put it: `-m PATH`,
/// `--model PATH` or `--model=PATH`. With no model file to key on, the key
/// falls back to the config tuple alone — the dedupe is then only as strong
/// as the command being identical, which is still stronger than a name.
///
/// The port is taken out of the config tuple (`--port N`, `--port=N`,
/// `-np N`, `-np=N`): the port is the instance's assigned fact, not a part
/// of what is being served. Everything else — the binary, the context size,
/// the batch flags — stays in, because flags that really differ are a
/// really different server.
pub fn key_for(command: &[String]) -> ServeKey {
    let mut model_flag: Option<String> = None;
    let mut config_tokens: Vec<&str> = Vec::new();
    let mut skip_next = false;
    for (index, token) in command.iter().enumerate() {
        if skip_next {
            skip_next = false;
            continue;
        }
        if let Some(value) = token.strip_prefix("--model=") {
            model_flag = Some(value.to_string());
            continue;
        }
        if token == "-m" || token == "--model" {
            if let Some(value) = command.get(index + 1) {
                model_flag = Some(value.clone());
                skip_next = true;
                continue;
            }
        }
        // The port is not a part of the served config.
        if token.strip_prefix("--port=").is_some() || token.strip_prefix("-np=").is_some() {
            continue;
        }
        if token == "--port" || token == "-np" {
            if command.get(index + 1).is_some() {
                skip_next = true;
                continue;
            }
        }
        config_tokens.push(token);
    }
    match model_flag
        .as_ref()
        .map(PathBuf::from)
        .and_then(|path| std::fs::canonicalize(path).ok())
    {
        Some(canonical) => {
            let config = config_tokens.join(" ");
            let hash = file_hash(&canonical)
                .map(|hash| format!("{hash:016x}"))
                .unwrap_or_else(|| "unreadable".to_string());
            ServeKey {
                key: format!("file:{}:{}|{}", canonical.display(), hash, config),
                model_file: Some(canonical),
                model_hash: Some(hash),
                config,
                basis: "file",
            }
        }
        None => {
            // No model file to key on. The model flag's raw value — a name
            // the server would resolve itself, or a path that is not there —
            // stays in the config tuple, so two different models cannot
            // collide behind the same key.
            let mut fallback = Vec::new();
            if let Some(model) = &model_flag {
                fallback.push(model.as_str());
            }
            fallback.extend(config_tokens.iter().copied());
            let config = fallback.join(" ");
            ServeKey {
                key: format!("command|{}", config),
                model_file: None,
                model_hash: None,
                config,
                basis: "command",
            }
        }
    }
}

/// A hash of a file's contents, streamed: FNV-1a 64. Not cryptography — a
/// fingerprint that says whether two paths hold the same bytes, cheaply
/// enough to compute per `serve` ask on multi-gigabyte weights.
fn file_hash(path: &Path) -> Option<u64> {
    let mut file = File::open(path).ok()?;
    let mut buffer = [0u8; 1024 * 1024];
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    loop {
        let read = file.read(&mut buffer).ok()?;
        if read == 0 {
            return Some(hash);
        }
        for byte in &buffer[..read] {
            hash ^= *byte as u64;
            hash = hash.wrapping_mul(0x0000_0100_0000_01b3);
        }
    }
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

    /// The server answering for one key, if it is answering.
    pub fn find(&self, key: &str) -> Option<ServerEntry> {
        self.live().into_iter().find(|entry| entry.key == key)
    }

    /// Record an entry, replacing any this key already has.
    ///
    /// The whole read-modify-write sits under the registry's flock, so two
    /// seats recording at once cannot lose one another's entry.
    pub fn record(&self, entry: ServerEntry) {
        self.with_lock(|entries| {
            entries.retain(|other| other.key != entry.key);
            entries.push(entry);
        });
    }

    /// Drop one key's entry.
    pub fn remove(&self, key: &str) {
        self.with_lock(|entries| entries.retain(|other| other.key != key));
    }

    /// Read the entries as they are written. Unreadable is empty: a torn
    /// file must not take the registry's memory of a running server with it.
    ///
    /// An entry written before the registry was keyed (round 8 keyed on the
    /// model's *name*) gets its old key back — `name:<model>` — so an entry
    /// written by an older `serve` still serves the seats that read it the
    /// old way, until its server goes and the entry goes with it.
    fn read(&self) -> Vec<ServerEntry> {
        File::open(&self.path)
            .map(|file| {
                BufReader::new(file)
                    .lines()
                    .map_while(Result::ok)
                    .filter(|line| !line.trim().is_empty())
                    .filter_map(|line| {
                        let mut entry: ServerEntry = serde_json::from_str(&line).ok()?;
                        if entry.key.is_empty() {
                            entry.key = format!("name:{}", entry.model);
                        }
                        Some(entry)
                    })
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

/// A new entry for a server that has just answered its port, keyed on what
/// the command identifies.
pub fn entry(key: &ServeKey, model: &str, port: u16) -> ServerEntry {
    ServerEntry {
        key: key.key.clone(),
        model: model.to_string(),
        port,
        model_file: key.model_file.as_ref().map(|path| path.display().to_string()),
        model_hash: key.model_hash.clone(),
        config: Some(key.config.clone()),
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

    /// A stand-in model file: the hash only needs two files' contents to
    /// differ when the files differ.
    fn model_file(dir: &Path, name: &str, contents: &[u8]) -> PathBuf {
        let path = dir.join(name);
        std::fs::write(&path, contents).unwrap();
        path
    }

    fn command_with(model: &Path, port: u16, extra: &[&str]) -> Vec<String> {
        let mut command = vec![
            "/opt/llama.cpp/bin/llama-server".to_string(),
            "-m".to_string(),
            model.display().to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
            "--port".to_string(),
            port.to_string(),
        ];
        command.extend(extra.iter().map(|token| token.to_string()));
        command
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

    /// The 01:19 incident: `d1-2B`, `d1-2B-baseline` and `d1-2B-batch` were
    /// three servers because the key was the name. The same model file with
    /// the same flags is one server under any three names.
    #[test]
    fn the_same_model_file_and_flags_are_one_key_under_any_name() {
        let dir = temp_dir("same-key");
        let model = model_file(&dir, "d1-2B.gguf", b"the weights");
        // Two asks, two ports, one difference: nothing that changes what is
        // served. The name a seat types is not in the key at all.
        let first = key_for(&command_with(&model, 8100, &["-c", "32768"]));
        let second = key_for(&command_with(&model, 8140, &["-c", "32768"]));
        assert_eq!(first.basis, "file");
        assert_eq!(first.key, second.key, "same file, same flags, same server");
        assert!(
            first.key.contains("d1-2B.gguf"),
            "the key names the model file: {}",
            first.key
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn flags_that_really_differ_ask_for_their_own_server() {
        let dir = temp_dir("variant-flags");
        let model = model_file(&dir, "d1-2B.gguf", b"the weights");
        let plain = key_for(&command_with(&model, 8100, &[]));
        let batched = key_for(&command_with(&model, 8100, &["-b", "32768", "-ub", "32768"]));
        assert_ne!(
            plain.key, batched.key,
            "a variant whose flags differ is a different server"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn different_weights_under_the_same_path_are_different_servers() {
        let dir = temp_dir("reweighted");
        let model = model_file(&dir, "model.gguf", b"version one");
        let first = key_for(&command_with(&model, 8100, &[]));
        std::fs::write(&model, b"version two, after the night's training").unwrap();
        let second = key_for(&command_with(&model, 8100, &[]));
        assert_ne!(
            first.key, second.key,
            "the same path with new contents is a new model"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_command_with_no_model_file_keys_on_the_command_itself() {
        let a = key_for(&[
            "llama-server".to_string(),
            "--port".to_string(),
            "8100".to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
        ]);
        let b = key_for(&[
            "llama-server".to_string(),
            "--port".to_string(),
            "8140".to_string(),
            "--host".to_string(),
            "127.0.0.1".to_string(),
        ]);
        assert_eq!(a.basis, "command");
        assert_eq!(a.key, b.key, "the port is not part of the config");
    }

    #[test]
    fn an_entry_whose_port_died_is_not_live() {
        let dir = temp_dir("dead-entry");
        let registry = Registry::new(&dir);
        let model = model_file(&dir, "d1-2B.gguf", b"the weights");
        let key = key_for(&command_with(&model, 8100, &[]));
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        registry.record(entry(&key, "d1-2B", port));
        assert!(registry.find(&key.key).is_some(), "the live server is found");
        // The server goes away; the file still says it is there.
        drop(listener);
        assert!(
            registry.find(&key.key).is_none(),
            "a dead server is still in the file: {:?}",
            std::fs::read_to_string(registry.path()).unwrap_or_default()
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn recording_twice_replaces_rather_than_doubles() {
        let dir = temp_dir("replace");
        let registry = Registry::new(&dir);
        let model = model_file(&dir, "d1-2B.gguf", b"the weights");
        let other = model_file(&dir, "qwen.gguf", b"other weights");
        let d1 = key_for(&command_with(&model, 8100, &[]));
        let qwen = key_for(&command_with(&other, 8200, &[]));
        registry.record(entry(&d1, "d1-2B", 8100));
        registry.record(entry(&d1, "d1-2B-baseline", 8101));
        registry.record(entry(&qwen, "qwen", 8200));
        let file = registry.read();
        assert_eq!(file.len(), 2, "one entry per key: {file:?}");
        assert!(
            file.iter()
                .any(|entry| entry.key == d1.key && entry.port == 8101)
        );
        registry.remove(&d1.key);
        assert_eq!(registry.read().len(), 1, "the key's entry is gone");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn an_entry_from_the_name_keyed_days_still_reads() {
        // Round 8's entries had no `key`. They keep working under the old
        // rule — find them by `name:<model>` — until their servers go.
        let dir = temp_dir("legacy-entry");
        let registry = Registry::new(&dir);
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::fs::write(
            registry.path(),
            format!("{{\"model\":\"d1-2B\",\"port\":{port},\"at\":\"2026-11-01T09:11:54Z\"}}\n"),
        )
        .unwrap();
        let found = registry.find("name:d1-2B");
        assert!(
            found.is_some() && found.unwrap().port == port,
            "the legacy entry is found under its old key"
        );
        drop(listener);
        assert!(registry.find("name:d1-2B").is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
