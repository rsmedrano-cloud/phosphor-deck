//! lib/dlog.py, the parts phosphor run actually calls: one capped, always-on
//! log (deck.log) and a per-tool verbose trace that turns itself off. Same
//! file, same format, same cap -- so `phosphor logs TOOL` reads either
//! writer's lines back exactly the same way, whether this ran or the
//! Python phosphor run did.
//!
//! Every function here takes the cache dir as a plain argument instead of
//! reading PHOSPHOR_CACHE itself: main() resolves it once
//! (cache_dir_from_env), and tests pass their own throwaway one, so
//! parallel `cargo test` runs never race on a shared env var.

use std::io::Write;

const CAP: u64 = 200 * 1024;

pub fn cache_dir_from_env() -> String {
    std::env::var("PHOSPHOR_CACHE").unwrap_or_else(|_| {
        format!("{}/.cache/phosphor", std::env::var("HOME").unwrap_or_else(|_| "/".into()))
    })
}

fn stamp() -> String {
    let out = std::process::Command::new("date").arg("+%Y-%m-%d %H:%M:%S").output();
    out.ok().and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "0000-00-00 00:00:00".to_string())
}

fn append_capped(path: &str, line: &str) {
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = f.write_all(line.as_bytes());
    }
    if let Ok(meta) = std::fs::metadata(path) {
        if meta.len() > CAP {
            if let Ok(text) = std::fs::read_to_string(path) {
                let lines: Vec<&str> = text.lines().collect();
                let half = lines[lines.len() / 2..].join("\n") + "\n";
                let _ = std::fs::write(path, half);
            }
        }
    }
}

/// One line in the base log: never a host name, a note, or anything past
/// what the caller already shows on screen -- deck.log is meant to be safe
/// to paste into an issue.
pub fn event(dir: &str, tool: &str, what: &str, detail: &str) {
    let _ = std::fs::create_dir_all(dir);
    let mut line = format!("{}  {:<10} {:<6}", stamp(), tool, what);
    if !detail.is_empty() {
        line.push(' ');
        line.push_str(detail);
    }
    line.push('\n');
    append_capped(&format!("{}/deck.log", dir), &line);
}

fn flag(dir: &str, tool: &str) -> String {
    format!("{}/trace-{}", dir, tool)
}

fn tracefile(dir: &str, tool: &str) -> String {
    format!("{}/trace-{}.log", dir, tool)
}

/// Is `tool`'s trace on right now? (`phosphor trace TOOL`, ~30 minutes.)
pub fn tracing(dir: &str, tool: &str) -> bool {
    let Ok(text) = std::fs::read_to_string(flag(dir, tool)) else { return false };
    let Ok(until) = text.trim().parse::<f64>() else { return false };
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
        .unwrap().as_secs_f64();
    if now >= until {
        let _ = std::fs::remove_file(flag(dir, tool));
        return false;
    }
    true
}

/// A verbose line for `tool`, kept only while its trace is on.
pub fn trace(dir: &str, tool: &str, msg: &str) {
    if !tracing(dir, tool) {
        return;
    }
    let line = format!("{}  {}\n", stamp(), msg);
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(tracefile(dir, tool)) {
        let _ = f.write_all(line.as_bytes());
    }
}

/// The last `n` base-log lines for `tool`, case-insensitive -- what `l` on
/// an ended pane shows (lib/dlog.py's tail_for).
pub fn tail_for(dir: &str, tool: &str, n: usize) -> Vec<String> {
    let path = format!("{}/deck.log", dir);
    let Ok(text) = std::fs::read_to_string(&path) else { return Vec::new() };
    let want = tool.to_lowercase();
    let matches: Vec<String> = text.lines()
        .filter(|line| {
            line.split_whitespace().nth(2).map(|t| t.to_lowercase()) == Some(want.clone())
        })
        .map(|l| l.to_string())
        .collect();
    let start = matches.len().saturating_sub(n);
    matches[start..].to_vec()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn isolated() -> String {
        let d = std::env::temp_dir().join(format!("run-dlog-test-{}-{}-{}",
            std::process::id(), line!(),
            std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos()));
        std::fs::create_dir_all(&d).unwrap();
        d.to_str().unwrap().to_string()
    }

    #[test]
    fn event_line_has_no_pid_leak_and_tail_for_finds_it_case_insensitively() {
        let d = isolated();
        event(&d, "BTOP", "exit", "1");
        event(&d, "YAZI", "hung", "");
        let back = tail_for(&d, "btop", 10);
        assert_eq!(back.len(), 1);
        assert!(back[0].contains("exit") && back[0].contains('1'));
        std::fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn tail_for_returns_only_the_last_n() {
        let d = isolated();
        for i in 0..5 {
            event(&d, "CTOP", "exit", &i.to_string());
        }
        let back = tail_for(&d, "ctop", 2);
        assert_eq!(back.len(), 2);
        assert!(back[1].ends_with('4'));
        std::fs::remove_dir_all(&d).ok();
    }

    #[test]
    fn trace_writes_nothing_when_tracing_is_off() {
        let d = isolated();
        trace(&d, "GPING", "should not appear");
        assert!(!std::path::Path::new(&tracefile(&d, "GPING")).exists());
        std::fs::remove_dir_all(&d).ok();
    }
}
