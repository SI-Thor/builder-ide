//! Argument parsing: `--flag value`, `--flag=value`, `--flag`, and
//! positional words. Deliberately tiny — no crate, no surprises.

pub struct Args {
    flags: Vec<(String, Option<String>)>,
    positional: Vec<String>,
}

impl Args {
    pub fn parse(argv: &[String]) -> Args {
        let mut flags: Vec<(String, Option<String>)> = Vec::new();
        let mut positional: Vec<String> = Vec::new();
        let mut i = 0;
        while i < argv.len() {
            let a = argv[i].clone();
            if let Some(rest) = a.strip_prefix("--") {
                if let Some(eq) = rest.find('=') {
                    flags.push((rest[..eq].to_string(), Some(rest[eq + 1..].to_string())));
                    i += 1;
                } else if i + 1 < argv.len() && !argv[i + 1].starts_with("--") {
                    flags.push((rest.to_string(), Some(argv[i + 1].clone())));
                    i += 2;
                } else {
                    flags.push((rest.to_string(), None));
                    i += 1;
                }
            } else {
                positional.push(a);
                i += 1;
            }
        }
        Args { flags, positional }
    }

    pub fn get(&self, key: &str) -> Option<&str> {
        self.flags
            .iter()
            .find(|(k, _)| k == key)
            .and_then(|(_, v)| v.as_deref())
    }

    /// Every value given for a repeatable flag, in order. A flag with no
    /// value (`--clause` alone) is skipped: it has nothing to say.
    pub fn get_all(&self, key: &str) -> Vec<&str> {
        self.flags
            .iter()
            .filter(|(k, _)| k == key)
            .filter_map(|(_, v)| v.as_deref())
            .collect()
    }

    pub fn has(&self, key: &str) -> bool {
        self.flags.iter().any(|(k, _)| k == key)
    }

    pub fn need(&self, key: &str) -> Result<&str, String> {
        self.get(key)
            .ok_or_else(|| format!("missing required flag --{}", key))
    }

    pub fn num(&self, key: &str) -> Result<Option<f64>, String> {
        match self.get(key) {
            None => Ok(None),
            Some(v) => v
                .parse::<f64>()
                .map(Some)
                .map_err(|_| format!("--{} wants a number, got '{}'", key, v)),
        }
    }

    pub fn need_num(&self, key: &str) -> Result<f64, String> {
        self.num(key)?
            .ok_or_else(|| format!("missing required flag --{}", key))
    }

    /// A duration in minutes, from `--<key>-min` or `--<key>-hours`.
    pub fn duration_min(&self, key: &str) -> Result<Option<f64>, String> {
        if let Some(v) = self.num(&format!("{}-min", key))? {
            return Ok(Some(v));
        }
        if let Some(v) = self.num(&format!("{}-hours", key))? {
            return Ok(Some(v * 60.0));
        }
        Ok(None)
    }

    pub fn word(&self, n: usize) -> Option<&str> {
        self.positional.get(n).map(|s| s.as_str())
    }
}
