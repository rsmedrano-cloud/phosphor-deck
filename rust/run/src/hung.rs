//! lib/hung.py, ported: tell a program that froze from one that's just
//! quiet. A TUI that deadlocks keeps its last frame on screen -- the pane
//! looks alive and says nothing. The sign that works for any program: the
//! terminal changed size, the kernel queued SIGWINCH, and the program
//! neither took it nor used any CPU for a while.

use std::collections::HashMap;
use std::time::Instant;

const WINCH: u64 = 1 << 27; // SIGWINCH (28) in /proc's signal masks

fn read(path: &str) -> Option<String> {
    std::fs::read_to_string(path).ok()
}

fn mask(status: &str, key: &str) -> u64 {
    for line in status.lines() {
        if let Some(rest) = line.strip_prefix(&format!("{}:", key)) {
            if let Some(hex) = rest.split_whitespace().next() {
                return u64::from_str_radix(hex, 16).unwrap_or(0);
            }
        }
    }
    0
}

fn waiting(status: &str) -> bool {
    let pend = mask(status, "SigPnd") | mask(status, "ShdPnd");
    (pend & WINCH != 0) && (mask(status, "SigBlk") & WINCH != 0)
}

/// `root` and every process below it. One pass over /proc.
fn tree(root: i32) -> Vec<i32> {
    let mut kids: HashMap<i32, Vec<i32>> = HashMap::new();
    if let Ok(entries) = std::fs::read_dir("/proc") {
        for e in entries.flatten() {
            let name = e.file_name();
            let Some(pid_str) = name.to_str() else { continue };
            if !pid_str.chars().all(|c| c.is_ascii_digit()) {
                continue;
            }
            let Some(st) = read(&format!("/proc/{}/stat", pid_str)) else { continue };
            let Some(after_comm) = st.rsplit_once(')') else { continue };
            let fields: Vec<&str> = after_comm.1.split_whitespace().collect();
            let Some(ppid) = fields.get(1).and_then(|s| s.parse::<i32>().ok()) else { continue };
            let pid: i32 = pid_str.parse().unwrap_or(0);
            kids.entry(ppid).or_default().push(pid);
        }
    }
    let mut out = Vec::new();
    let mut todo = vec![root];
    while let Some(p) = todo.pop() {
        out.push(p);
        if let Some(c) = kids.get(&p) {
            todo.extend(c);
        }
    }
    out
}

/// {pid: cpu ticks} of these processes, on this terminal, that have a
/// resize waiting in every thread.
fn stuck(pids: &[i32], tty: u64) -> HashMap<i32, u64> {
    let mut found = HashMap::new();
    for &pid in pids {
        let Some(st) = read(&format!("/proc/{}/stat", pid)) else { continue };
        let Some((_, after)) = st.rsplit_once(')') else { continue };
        let f: Vec<&str> = after.split_whitespace().collect();
        // f[0]=state f[1]=ppid f[2]=pgrp f[3]=session f[4]=tty_nr ... f[11]=utime f[12]=stime
        let Some(state) = f.first() else { continue };
        let Some(&tty_nr) = f.get(4) else { continue };
        let Ok(tty_nr) = tty_nr.parse::<u64>() else { continue };
        if tty_nr != tty || "TtZX".contains(state.chars().next().unwrap_or(' ')) {
            continue; // elsewhere, Ctrl-Z'd, finished
        }
        let Ok(tasks) = std::fs::read_dir(format!("/proc/{}/task", pid)) else { continue };
        let mut texts = Vec::new();
        let mut any = false;
        for t in tasks.flatten() {
            any = true;
            let tid = t.file_name();
            match read(&format!("/proc/{}/task/{}/status", pid, tid.to_string_lossy())) {
                Some(s) => texts.push(s),
                None => texts.push(String::new()),
            }
        }
        if any && texts.iter().all(|t| !t.is_empty() && waiting(t)) {
            let utime: u64 = f.get(11).and_then(|s| s.parse().ok()).unwrap_or(0);
            let stime: u64 = f.get(12).and_then(|s| s.parse().ok()).unwrap_or(0);
            found.insert(pid, utime + stime);
        }
    }
    found
}

/// Call tick() every few seconds; it returns the pid that's been stuck, with
/// no CPU spent, for `after` seconds, else None.
pub struct Watch {
    root: i32,
    tty: u64,
    after: f64,
    rescan: f64,
    seen: HashMap<i32, (Instant, u64)>,
    pids: Vec<i32>,
    listed: Option<Instant>,
}

impl Watch {
    pub fn new(root: i32, tty: u64, after: f64) -> Self {
        Watch { root, tty, after, rescan: 30.0, seen: HashMap::new(), pids: Vec::new(), listed: None }
    }

    pub fn tick(&mut self, now: Instant) -> Option<i32> {
        if self.listed.map(|l| now.duration_since(l).as_secs_f64() >= self.rescan).unwrap_or(true) {
            self.pids = tree(self.root);
            self.listed = Some(now);
        }
        let cur = stuck(&self.pids, self.tty);
        self.seen.retain(|p, (_, cpu)| cur.get(p) == Some(cpu));
        for (&p, &cpu) in cur.iter() {
            self.seen.entry(p).or_insert((now, cpu));
        }
        for (_, (since, _)) in self.seen.iter() {
            if now.duration_since(*since).as_secs_f64() >= self.after {
                return self.seen.iter().find(|(_, (s, _))| s == since).map(|(&p, _)| p);
            }
        }
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mask_reads_a_proc_status_hex_field() {
        let status = "Name:\tbash\nSigPnd:\t0000000000000000\nSigBlk:\t0000000008000000\n";
        assert_eq!(mask(status, "SigBlk"), WINCH);
        assert_eq!(mask(status, "SigPnd"), 0);
        assert_eq!(mask(status, "Missing"), 0);
    }

    #[test]
    fn waiting_needs_both_pending_and_blocked() {
        let both = "SigPnd:\t0000000008000000\nSigBlk:\t0000000008000000\n";
        let only_blocked = "SigPnd:\t0000000000000000\nSigBlk:\t0000000008000000\n";
        assert!(waiting(both));
        assert!(!waiting(only_blocked));
    }

    #[test]
    fn tree_finds_this_process_and_a_real_child() {
        let child = std::process::Command::new("sleep").arg("30").spawn().unwrap();
        let pid = child.id() as i32;
        std::thread::sleep(std::time::Duration::from_millis(100));
        let mine = std::process::id() as i32;
        let t = tree(mine);
        assert!(t.contains(&mine));
        assert!(t.contains(&pid), "tree(my pid) should include a real child of mine");
        let _ = std::process::Command::new("kill").arg(pid.to_string()).status();
    }

    #[test]
    fn watch_never_fires_on_a_healthy_process() {
        // No real terminal in a test process (tty 0 matches nothing real):
        // stuck() should find nothing, so tick() never returns a pid.
        let mut w = Watch::new(std::process::id() as i32, 999_999, 0.01);
        for _ in 0..3 {
            assert_eq!(w.tick(Instant::now()), None);
        }
    }
}
