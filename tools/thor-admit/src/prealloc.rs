//! The preallocation rule: which frameworks take the box's memory before
//! anybody asked them to.
//!
//! **The mechanism.** On a discrete GPU, JAX/XLA's preallocation takes a
//! **private pool** on the card, and the rest of the machine never notices.
//! On the Thor the GPU's memory **is** the system's memory: the same
//! preallocation — `XLA_PYTHON_CLIENT_PREALLOCATE` defaults to true, and the
//! default fraction is 75–90 % — takes **most of the machine's RAM** before
//! the program computes anything. That is what hung the Thor on 2026-11-01:
//! a MJX run held **94.5 GB in 20 seconds**, the desktop died, the Wi-Fi
//! driver died, and the box needed a power cycle (see
//! `docs/lab/incident-2026-11-01-jax-hang.md`).
//!
//! **What this module does.** It reads a command line and says whether it
//! starts a framework that preallocates, and it says whether the environment
//! has been made safe for it. It is the client half of round 12: the daemon's
//! guard catches a runaway after it has started, and this catches it before.
//!
//! **What "safe" means.** The framework may still be started, when its
//! allocator has been told not to take the box by surprise:
//!
//! * JAX/XLA — `XLA_PYTHON_CLIENT_PREALLOCATE=false`, or
//!   `XLA_PYTHON_CLIENT_ALLOCATOR=platform` (the platform allocator grows on
//!   demand), or `XLA_PYTHON_CLIENT_MEM_FRACTION` at most **0.15**, the
//!   house rule's number (0.15 of 122.8 GiB is about 18 GiB).
//! * TensorFlow — `TF_FORCE_GPU_ALLOW_GROWTH=true`, the growth allocator.
//!
//! PyTorch is **not** on the list: its caching allocator grows on demand and
//! does not take the box by surprise. It is still work that belongs under a
//! lease, which is a different rule (the memory rule) and not this one.

use std::path::Path;

/// What has to be true of the environment for a framework to be safe.
pub enum Safety {
    /// The variable must be set to one of these values.
    Exact(&'static [(&'static str, &'static str)]),
    /// The variable must be set to a number no larger than this.
    AtMost(&'static str, f64),
}

/// A framework that preallocates.
pub struct Framework {
    /// The name an operator would call it.
    pub name: &'static str,
    /// The module that gives it away in a script.
    pub marker: &'static str,
    /// What makes it safe.
    pub rules: &'static [Safety],
}

/// The frameworks that take the box's memory by surprise.
pub const FRAMEWORKS: &[Framework] = &[
    Framework {
        name: "JAX/XLA",
        marker: "jax",
        rules: &[
            Safety::Exact(&[
                ("XLA_PYTHON_CLIENT_PREALLOCATE", "false"),
                ("XLA_PYTHON_CLIENT_ALLOCATOR", "platform"),
            ]),
            Safety::AtMost("XLA_PYTHON_CLIENT_MEM_FRACTION", 0.15),
        ],
    },
    Framework {
        name: "TensorFlow",
        marker: "tensorflow",
        rules: &[Safety::Exact(&[("TF_FORCE_GPU_ALLOW_GROWTH", "true")])],
    },
];

/// What was found, and where it was found.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Detected {
    /// The framework.
    pub framework: &'static str,
    /// How the command line gave it away.
    pub evidence: String,
}

/// Does this text import the module?
///
/// The match is on the **import statement**, not on the word: `import jax`
/// and `import jax.numpy` are the framework, and `import jaxlib` is not —
/// `jaxlib` is the compiler library, and importing it allocates nothing. The
/// word boundary is what tells them apart, so the check is a word match and
/// not a substring match.
fn imports(text: &str, marker: &str) -> bool {
    let dotted = format!("{marker}.");
    for line in text.lines() {
        let line = line.trim_start();
        // A commented-out import is not an import.
        if line.starts_with('#') {
            continue;
        }
        // Everything up to a comment marker is the statement.
        let statement = line.split('#').next().unwrap_or(line);
        // One line may hold several statements.
        for part in statement.split(';') {
            let part = part.trim();
            let names: Vec<&str> = if let Some(after) = part.strip_prefix("import ") {
                after.split(',').map(|name| name.trim()).collect()
            } else if let Some(after) = part.strip_prefix("from ") {
                // `from jax.numpy import x` — the module is the first word.
                vec![after.split_whitespace().next().unwrap_or("")]
            } else {
                continue;
            };
            for name in names {
                // `import jax.numpy as jnp` — the alias is not part of the name.
                let name = name.split_whitespace().next().unwrap_or("");
                if name == marker || name.starts_with(&dotted) {
                    return true;
                }
            }
        }
    }
    false
}

/// Read the head of a script and look at it.
///
/// Sixty-four kibibytes is enough for the imports of any ordinary script, and
/// it keeps a stray four-gigabyte data file from being read into memory.
fn script_imports(path: &Path, marker: &str) -> bool {
    let Ok(text) = std::fs::read_to_string(path) else {
        return false;
    };
    let head: String = text.chars().take(64 * 1024).collect();
    imports(&head, marker)
}

/// What the command line starts, and what gave the framework away.
pub fn detect(command: &[String]) -> Option<Detected> {
    let Some(program) = command.first() else {
        return None;
    };
    let program_name = program.rsplit('/').next().unwrap_or(program);

    // The program itself is the framework: `jax`, `tensorflow`.
    for framework in FRAMEWORKS {
        if program_name == framework.marker {
            return Some(Detected {
                framework: framework.name,
                evidence: format!("the program is {program_name}"),
            });
        }
    }

    let mut index = 1;
    while index < command.len() {
        let argument = &command[index];
        match argument.as_str() {
            // `python -m jax.something`: the module is named outright.
            "-m" | "--module" => {
                let module = command.get(index + 1)?;
                for framework in FRAMEWORKS {
                    if module == framework.marker
                        || module.starts_with(&format!("{}.", framework.marker))
                    {
                        return Some(Detected {
                            framework: framework.name,
                            evidence: format!("the command runs the module {module}"),
                        });
                    }
                }
                index += 2;
                continue;
            }
            // `python -c "import jax"`: the code is in the argument.
            "-c" => {
                let code = command.get(index + 1)?;
                for framework in FRAMEWORKS {
                    if imports(code, framework.marker) {
                        return Some(Detected {
                            framework: framework.name,
                            evidence: "the inline code imports it".to_string(),
                        });
                    }
                }
                index += 2;
                continue;
            }
            _ => {}
        }
        // `python train.py`: the script is a file on disk, and the file says
        // what it imports. The incident's run was `train_spike.py
        // --backend mjx --nworld 256` — the name says nothing, the file says
        // `import jax`.
        if argument.ends_with(".py") {
            let path = Path::new(argument);
            if path.exists() {
                for framework in FRAMEWORKS {
                    if script_imports(path, framework.marker) {
                        return Some(Detected {
                            framework: framework.name,
                            evidence: format!("the script {argument} imports it"),
                        });
                    }
                }
            }
        }
        index += 1;
    }
    None
}

/// Is the environment safe for this framework?
///
/// `Ok(reason)` says it is, and says why. `Err(reason)` says it is not, and
/// says what would make it so.
pub fn safety(
    framework: &Framework,
    get: &dyn Fn(&str) -> Option<String>,
) -> Result<String, String> {
    for rule in framework.rules {
        match rule {
            Safety::Exact(options) => {
                for (variable, wanted) in options.iter() {
                    if let Some(value) = get(variable) {
                        if value.trim().eq_ignore_ascii_case(wanted) {
                            return Ok(format!("{variable}={value}"));
                        }
                    }
                }
            }
            Safety::AtMost(variable, limit) => {
                if let Some(value) = get(variable) {
                    if let Ok(number) = value.trim().parse::<f64>() {
                        if number.is_finite() && number > 0.0 && number <= *limit {
                            return Ok(format!("{variable}={value}"));
                        }
                    }
                }
            }
        }
    }
    Err(describe(framework))
}

/// What would make this framework safe.
pub fn describe(framework: &Framework) -> String {
    let mut lines = Vec::new();
    for rule in framework.rules {
        match rule {
            Safety::Exact(options) => {
                for (variable, wanted) in options.iter() {
                    lines.push(format!("{variable}={wanted}"));
                }
            }
            Safety::AtMost(variable, limit) => {
                lines.push(format!("{variable}={limit}"));
            }
        }
    }
    lines.join(" or ")
}

/// The refusal, with the reason and the ways out.
pub fn refusal(detected: &Detected, command: &[String]) -> String {
    let framework = FRAMEWORKS
        .iter()
        .find(|framework| framework.name == detected.framework)
        .expect("a detected framework is one of the known ones");
    let mut text = format!(
        "thor-admit: refusing to start a {} process without a safe allocator.\n",
        detected.framework
    );
    text.push_str(&format!("  found: {}\n", detected.evidence));
    text.push_str(
        "  why:   on this box the GPU's memory is the system's memory, and this framework\n\
         \x20        preallocates 75-90% of it before it computes anything. That is what\n\
         \x20        hung the Thor on 2026-11-01: 94.5 GB in 20 seconds, the desktop died,\n\
         \x20        the Wi-Fi driver died, and the box needed a power cycle.\n",
    );
    text.push_str(&format!(
        "  make it safe with one of: {}\n",
        describe(framework)
    ));
    text.push_str("    or run it under a lease, which is the rule for heavy work:\n");
    text.push_str(&format!(
        "      thor-admit run --peak 16G --label {} -- {}\n",
        framework.marker,
        command.join(" ")
    ));
    text.push_str("  (--allow-preallocation overrides this, and says so loudly.)");
    text
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn argv(parts: &[&str]) -> Vec<String> {
        parts.iter().map(|part| part.to_string()).collect()
    }

    #[test]
    fn a_plain_command_is_not_a_framework() {
        assert!(detect(&argv(&["python", "train.py"])).is_none());
        assert!(detect(&argv(&["sleep", "30"])).is_none());
        assert!(detect(&argv(&[])).is_none());
    }

    #[test]
    fn the_module_is_named_outright() {
        let detected = detect(&argv(&["python", "-m", "jax.something"])).unwrap();
        assert_eq!(detected.framework, "JAX/XLA");
    }

    #[test]
    fn inline_code_that_imports_jax_is_caught() {
        let detected = detect(&argv(&["python", "-c", "import jax; jax.numpy.ones(3)"])).unwrap();
        assert_eq!(detected.framework, "JAX/XLA");
    }

    #[test]
    fn jaxlib_is_not_jax() {
        assert!(detect(&argv(&["python", "-c", "import jaxlib"])).is_none());
    }

    #[test]
    fn tensorflow_is_caught_too() {
        let detected = detect(&argv(&["python", "-c", "import tensorflow as tf"])).unwrap();
        assert_eq!(detected.framework, "TensorFlow");
    }

    #[test]
    fn a_script_on_disk_is_read_for_its_imports() {
        let directory = std::env::temp_dir().join(format!("thor-admit-prealloc-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let script = directory.join("train_spike.py");
        std::fs::write(&script, "import os\nimport jax\nprint(jax.devices())\n").unwrap();
        let detected = detect(&argv(&["python", script.to_str().unwrap()])).unwrap();
        assert_eq!(detected.framework, "JAX/XLA");
        assert!(detected.evidence.contains("train_spike.py"));
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn a_script_that_imports_nothing_special_is_not_caught() {
        let directory = std::env::temp_dir().join(format!("thor-admit-prealloc-b-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let script = directory.join("plain.py");
        std::fs::write(&script, "import os\nprint(os.getpid())\n").unwrap();
        assert!(detect(&argv(&["python", script.to_str().unwrap()])).is_none());
        let _ = std::fs::remove_dir_all(&directory);
    }

    #[test]
    fn preallocate_false_is_safe() {
        let jax = &FRAMEWORKS[0];
        let environment: HashMap<String, String> =
            HashMap::from([("XLA_PYTHON_CLIENT_PREALLOCATE".to_string(), "false".to_string())]);
        let reason = safety(jax, &|key: &str| environment.get(key).cloned()).unwrap();
        assert!(reason.contains("PREALLOCATE"));
    }

    #[test]
    fn the_platform_allocator_is_safe() {
        let jax = &FRAMEWORKS[0];
        let environment: HashMap<String, String> =
            HashMap::from([("XLA_PYTHON_CLIENT_ALLOCATOR".to_string(), "platform".to_string())]);
        assert!(safety(jax, &|key: &str| environment.get(key).cloned()).is_ok());
    }

    #[test]
    fn a_small_memory_fraction_is_safe_and_a_large_one_is_not() {
        let jax = &FRAMEWORKS[0];
        let small: HashMap<String, String> =
            HashMap::from([("XLA_PYTHON_CLIENT_MEM_FRACTION".to_string(), "0.15".to_string())]);
        assert!(safety(jax, &|key: &str| small.get(key).cloned()).is_ok());
        let large: HashMap<String, String> =
            HashMap::from([("XLA_PYTHON_CLIENT_MEM_FRACTION".to_string(), "0.75".to_string())]);
        assert!(safety(jax, &|key: &str| large.get(key).cloned()).is_err());
    }

    #[test]
    fn preallocate_true_is_not_safe() {
        let jax = &FRAMEWORKS[0];
        let environment: HashMap<String, String> =
            HashMap::from([("XLA_PYTHON_CLIENT_PREALLOCATE".to_string(), "true".to_string())]);
        assert!(safety(jax, &|key: &str| environment.get(key).cloned()).is_err());
    }

    #[test]
    fn tensorflow_needs_the_growth_allocator() {
        let tensorflow = &FRAMEWORKS[1];
        let environment: HashMap<String, String> =
            HashMap::from([("TF_FORCE_GPU_ALLOW_GROWTH".to_string(), "true".to_string())]);
        assert!(safety(tensorflow, &|key: &str| environment.get(key).cloned()).is_ok());
        assert!(safety(tensorflow, &|_: &str| None).is_err());
    }
}
