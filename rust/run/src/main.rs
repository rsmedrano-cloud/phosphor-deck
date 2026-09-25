//! phosphor-run -- an optional Rust rewrite of lib/run.py, the watcher every
//! pane in the deck runs through. Not wired into gen.py yet: this binary is
//! meant to be tried on a tab by hand (`cmd = "rust/run/target/release/
//! phosphor-run"` in the profile) before it's ever considered a default.
//!
//! Ported 1:1 from lib/run.py: the spawn/watch/banner/ask loop, hang
//! detection (hung.rs, from lib/hung.py), and dlog (dlog.rs, from
//! lib/dlog.py) are all here. Two things are deliberately NOT reimplemented:
//!
//! - **Mouse taps.** lib/run.py's "kept tab" prompt also accepts a tap on
//!   its own row (cursor_row(), a DSR query). This binary is keyboard-only
//!   for now -- Enter/x/f/l always work, tapping the row doesn't yet.
//! - **Editing the profile.** A kept tab's "f" (forget it, out of your
//!   profile) needs lib/tabs.py's comment-preserving text surgery on
//!   deck.toml. Reimplementing that without its test coverage isn't a risk
//!   worth taking for this pane's rare last-program-ended case, so this
//!   shells out to `phosphor tabs --forget NAME` (and --closing, to ask
//!   whether this even is that case) instead of touching the profile
//!   itself. See tests/tabs-check.py for that side.
mod dlog;
mod hung;
mod theme;

use std::io::Write;
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

struct Args {
    name: Option<String>,
    reconnect: bool,
    wait: f64,
    alt: bool,
    cmd: Vec<String>,
}

fn parse_args(argv: &[String]) -> Option<Args> {
    let mut a = Args { name: None, reconnect: false, wait: 0.0, alt: false, cmd: Vec::new() };
    let mut i = 0;
    while i < argv.len() && argv[i] != "--" {
        match argv[i].as_str() {
            "--name" => { i += 1; a.name = argv.get(i).cloned(); }
            "--reconnect" => a.reconnect = true,
            "--wait" => { i += 1; a.wait = argv.get(i).and_then(|s| s.parse().ok()).unwrap_or(0.0); }
            "--alt" => a.alt = true,
            _ => {}
        }
        i += 1;
    }
    if i < argv.len() && argv[i] == "--" { i += 1; }
    a.cmd = argv[i..].to_vec();
    if a.cmd.is_empty() { return None; }
    if a.name.is_none() {
        let base = std::path::Path::new(&a.cmd[0]).file_name()
            .map(|s| s.to_string_lossy().to_uppercase()).unwrap_or_default();
        a.name = Some(base);
    }
    Some(a)
}

/// The profile's own `[deck] theme`, read straight (no host list, no
/// gauges to worry about here) -- PHOSPHOR_THEME still wins over this, same
/// order as lib/ui.py.theme_name().
fn profile_theme() -> Option<String> {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    let path = std::env::var("PHOSPHOR_PROFILE")
        .unwrap_or_else(|_| format!("{}/.config/phosphor/deck.toml", home));
    let text = std::fs::read_to_string(path).ok()?;
    let v: toml::Value = toml::from_str(&text).ok()?;
    v.get("deck")?.get("theme")?.as_str().map(|s| s.to_string())
}

fn phosphor_bin() -> String {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    let p = format!("{}/.local/bin/phosphor", home);
    if std::path::Path::new(&p).exists() { p } else { "phosphor".to_string() }
}

/// The kept tab this pane is the last program of, if any -- `phosphor tabs
/// --closing` (see this file's module docs for why that's a subprocess
/// instead of reimplemented profile/zellij-JSON parsing here).
fn closing() -> Option<String> {
    if std::env::var("ZELLIJ").is_err() {
        return None;
    }
    let out = Command::new(phosphor_bin()).args(["tabs", "--closing"]).output().ok()?;
    let s = String::from_utf8_lossy(&out.stdout).trim().to_string();
    if s.is_empty() { None } else { Some(s) }
}

fn forget(name: &str) -> Result<(), String> {
    let out = Command::new(phosphor_bin()).args(["tabs", "--forget", name]).output()
        .map_err(|e| e.to_string())?;
    if out.status.success() { Ok(()) }
    else { Err(String::from_utf8_lossy(&out.stdout).trim().to_string()) }
}

// ---- raw terminal ----------------------------------------------------

fn tcgetattr(fd: i32) -> Option<libc::termios> {
    unsafe {
        let mut t: libc::termios = std::mem::zeroed();
        if libc::tcgetattr(fd, &mut t) == 0 { Some(t) } else { None }
    }
}

fn tcsetattr(fd: i32, t: &libc::termios) {
    unsafe { libc::tcsetattr(fd, libc::TCSADRAIN, t); }
}

fn raw_mode<T>(f: impl FnOnce() -> T) -> T {
    let fd = 0;
    let old = tcgetattr(fd);
    if let Some(old) = old {
        let mut raw = old;
        unsafe { libc::cfmakeraw(&mut raw); }
        unsafe { libc::tcsetattr(fd, libc::TCSANOW, &raw); }
        let r = f();
        tcsetattr(fd, &old);
        r
    } else {
        f()
    }
}

/// One key, read straight from fd 0, `timeout` seconds (None: forever).
/// Not full lib/ui.py.getkey() parity (no mouse/escape-sequence decoding --
/// see this file's module docs): enough for Enter/x/f/l and "any other key".
fn getkey(timeout: Option<f64>) -> Option<String> {
    raw_mode(|| {
        let mut pfd = libc::pollfd { fd: 0, events: libc::POLLIN, revents: 0 };
        let ms = timeout.map(|t| (t * 1000.0) as i32).unwrap_or(-1);
        let r = unsafe { libc::poll(&mut pfd, 1, ms) };
        if r <= 0 { return None; }
        let mut buf = [0u8; 64];
        let n = unsafe { libc::read(0, buf.as_mut_ptr() as *mut libc::c_void, buf.len()) };
        if n <= 0 { return None; }
        Some(String::from_utf8_lossy(&buf[..n as usize]).to_string())
    })
}

fn sane() {
    print!("\x1b[0m\x1b[?25h\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l");
    let _ = std::io::stdout().flush();
    let _ = Command::new("stty").arg("sane").stderr(Stdio::null()).status();
}

fn banner(pal: &theme::Palette, name: &str, text: &str, color: &str) {
    print!("\n{}\x1b[7m {} \x1b[0m {}{}{}\n\n", color, name, color, text, pal.rst);
    let _ = std::io::stdout().flush();
}

/// (new consecutive-failure count, seconds to wait) for --reconnect's next
/// retry. `lasted`: how long the last attempt actually ran before dropping --
/// a real connection (up 30s+) forgives the streak, one that never came up
/// at all keeps doubling the wait, capped at 60s, so a link that's really
/// down doesn't get hammered every 3s for hours on end (a real outage did
/// exactly 2055 of those once). 1:1 with lib/run.py's reconnect_delay().
fn reconnect_delay(fails: u32, lasted: f64) -> (u32, u64) {
    let fails = if lasted > 30.0 { 0 } else { fails + 1 };
    (fails, (3u64 << fails.saturating_sub(1)).min(60))
}

#[cfg(test)]
mod reconnect_tests {
    use super::*;

    #[test]
    fn escalates_then_caps_at_60s() {
        let mut fails = 0u32;
        let mut delays = Vec::new();
        for _ in 0..8 {
            let (f, d) = reconnect_delay(fails, 0.1);
            fails = f;
            delays.push(d);
        }
        assert_eq!(delays, vec![3, 6, 12, 24, 48, 60, 60, 60]);
        assert_eq!(fails, 8);
    }

    #[test]
    fn a_real_connection_resets_the_streak() {
        let (fails, _) = reconnect_delay(5, 0.1);
        assert_eq!(fails, 6);
        let (fails, delay) = reconnect_delay(fails, 45.0);
        assert_eq!(fails, 0);
        assert_eq!(delay, 3, "the very next drop after a reset is a plain 3s, not capped");
    }

    #[test]
    fn thirty_seconds_exactly_does_not_count_as_a_real_connection() {
        let (fails, _) = reconnect_delay(2, 30.0);
        assert_eq!(fails, 3);
    }
}

fn keys_line(pal: &theme::Palette, pairs: &[(&str, &str)]) {
    let s: Vec<String> = pairs.iter()
        .map(|(k, v)| format!("{}{}{}  {}{}{}", pal.amb, k, pal.rst, pal.fg, v, pal.rst))
        .collect();
    println!("   {}", s.join("      "));
    let _ = std::io::stdout().flush();
}

fn show_log(name: &str, cache_dir: &str, pal: &theme::Palette) {
    let lines = dlog::tail_for(cache_dir, name, 12);
    println!("\n{}-- phosphor logs {} {}{}", pal.dim, name.to_lowercase(), "-".repeat(20), pal.rst);
    if lines.is_empty() {
        println!("  {}(nothing logged for {} yet){}", pal.dim, name, pal.rst);
    } else {
        for l in lines { println!("  {}{}{}", pal.dim, l, pal.rst); }
    }
    println!();
    let _ = std::io::stdout().flush();
}

/// Enter again, x close, f forget (only offered for a kept tab), l the log.
fn ask(pal: &theme::Palette, name: &str, cache_dir: &str, offer_forget: bool) -> &'static str {
    loop {
        match getkey(None).as_deref() {
            Some("\r") | Some("\n") | Some("r") => return "again",
            Some("x") | Some("X") => return "close",
            Some("f") | Some("F") if offer_forget => return "forget",
            Some("l") | Some("L") => show_log(name, cache_dir, pal),
            None => continue,
            _ => continue,
        }
    }
}

fn tty_rdev() -> Option<u64> {
    unsafe {
        if libc::isatty(0) == 0 { return None; }
        let mut st: libc::stat = std::mem::zeroed();
        if libc::fstat(0, &mut st) == 0 { Some(st.st_rdev as u64) } else { None }
    }
}

/// Wait for the child; close it if it froze. (exit code, froze).
fn watch(child: &mut std::process::Child, tty: Option<u64>) -> (i32, bool) {
    let after: f64 = std::env::var("PHOSPHOR_HANG_SECONDS").ok()
        .and_then(|s| s.parse().ok()).unwrap_or(20.0);
    let mut w = tty.filter(|_| after > 0.0).map(|t| hung::Watch::new(child.id() as i32, t, after));
    loop {
        match child.try_wait() {
            Ok(Some(status)) => return (status.code().unwrap_or(-1), false),
            Ok(None) => {}
            Err(_) => return (-1, false),
        }
        let Some(watcher) = w.as_mut() else {
            std::thread::sleep(Duration::from_millis(200));
            continue;
        };
        let step_ms: u64 = if after > 0.0 { ((after * 500.0) as u64).min(3000) } else { 200 };
        std::thread::sleep(Duration::from_millis(step_ms));
        let Some(pid) = watcher.tick(Instant::now()) else { continue };
        for sig in [libc::SIGTERM, libc::SIGKILL] {
            for p in [pid, child.id() as i32] {
                unsafe { libc::kill(p, sig); }
            }
            std::thread::sleep(Duration::from_millis(300));
            if let Ok(Some(status)) = child.try_wait() {
                return (status.code().unwrap_or(-1), true);
            }
        }
        if let Ok(status) = child.wait() {
            return (status.code().unwrap_or(-1), true);
        }
        return (-1, true);
    }
}

fn main() {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    let Some(args) = parse_args(&argv) else {
        eprintln!("usage: phosphor-run [--name N] [--reconnect] [--wait S] [--alt] -- CMD ARGS...");
        std::process::exit(2);
    };
    let name = args.name.clone().unwrap();
    let cache_dir = dlog::cache_dir_from_env();
    let pal = theme::resolve(std::env::var("PHOSPHOR_THEME").ok().as_deref(), profile_theme().as_deref());

    if args.wait > 0.0 {
        std::thread::sleep(Duration::from_secs_f64(args.wait));
    }

    let mut fails: u32 = 0;   // consecutive drops with no real connection in between
    loop {
        if args.alt {
            print!("\x1b[?1049h");
            let _ = std::io::stdout().flush();
        }
        unsafe {
            libc::signal(libc::SIGINT, libc::SIG_IGN);
            libc::signal(libc::SIGQUIT, libc::SIG_IGN);
        }

        if dlog::tracing(&cache_dir, &name) {
            dlog::trace(&cache_dir, &name, &format!("start: {}", args.cmd.join(" ")));
        }

        let tty = tty_rdev();
        let mut cmd = Command::new(&args.cmd[0]);
        cmd.args(&args.cmd[1..]);
        unsafe {
            cmd.pre_exec(|| {
                libc::signal(libc::SIGINT, libc::SIG_DFL);
                libc::signal(libc::SIGQUIT, libc::SIG_DFL);
                Ok(())
            });
        }
        let started = Instant::now();
        let (rc, froze, missing, broke);
        match cmd.spawn() {
            Ok(mut child) => {
                let (code, f) = watch(&mut child, tty);
                rc = code; froze = f; missing = false; broke = None;
            }
            Err(e) => {
                let not_found = matches!(e.kind(), std::io::ErrorKind::NotFound | std::io::ErrorKind::PermissionDenied);
                rc = if not_found { 127 } else { 1 };
                froze = false; missing = not_found;
                broke = if not_found { None } else { Some(e.to_string()) };
            }
        }
        unsafe {
            libc::signal(libc::SIGINT, libc::SIG_DFL);
            libc::signal(libc::SIGQUIT, libc::SIG_DFL);
        }
        if args.alt {
            print!("\x1b[?1049l");
        }
        sane();
        if dlog::tracing(&cache_dir, &name) {
            dlog::trace(&cache_dir, &name, &format!("rc={} froze={} missing={} broke={}", rc, froze, missing, broke.is_some()));
        }

        if args.reconnect && rc == 255 {
            let (f, delay) = reconnect_delay(fails, started.elapsed().as_secs_f64());
            fails = f;
            let msg = format!("connection lost: reconnecting in {}s", delay);
            dlog::event(&cache_dir, &name, "dropped", &format!("reconnecting in {}s", delay));
            banner(&pal, &name, &msg, pal.amb);
            keys_line(&pal, &[("x", "close this tab")]);
            if getkey(Some(delay as f64)).as_deref().map(|k| k == "x" || k == "X").unwrap_or(false) {
                std::process::exit(0);
            }
            continue;
        }

        let mut again = "open it again";
        if froze {
            dlog::event(&cache_dir, &name, "hung", "");
            banner(&pal, &name, "stopped responding, so it was closed", pal.red);
        } else if missing {
            banner(&pal, &name, &format!("couldn't start: {} isn't installed",
                std::path::Path::new(&args.cmd[0]).file_name().map(|s| s.to_string_lossy().to_string()).unwrap_or_default()), pal.red);
            again = "try again";
        } else if let Some(e) = &broke {
            dlog::event(&cache_dir, &name, "crash", &e[..e.len().min(200)]);
            banner(&pal, &name, &format!("phosphor run hit a problem watching it: see phosphor logs {}", name.to_lowercase()), pal.red);
        } else {
            if rc != 0 { dlog::event(&cache_dir, &name, "exit", &rc.to_string()); }
            let ssh_like = args.reconnect || args.cmd[0].ends_with("ssh");
            let what = if ssh_like { format!("you left {}", name.to_lowercase()) }
                       else if rc == 0 { "ended".to_string() } else { format!("ended (exit {})", rc) };
            banner(&pal, &name, &what, if rc == 0 { pal.amb } else { pal.red });
        }

        let kept = closing();
        let answer = if let Some(tab) = &kept {
            keys_line(&pal, &[("Enter", again), ("x", "close it for now (back after a restart)"),
                              ("f", "close it and forget it: out of your profile"), ("l", "see the log")]);
            let a = ask(&pal, &name, &cache_dir, true);
            if a == "forget" {
                if let Err(err) = forget(tab) {
                    println!("   {}{}{}", pal.red, err, pal.rst);
                    let _ = std::io::stdout().flush();
                    std::thread::sleep(Duration::from_secs(3));
                }
                std::process::exit(0);
            }
            a
        } else {
            keys_line(&pal, &[("Enter", again), ("x", "close this tab"), ("l", "see the log")]);
            ask(&pal, &name, &cache_dir, false)
        };
        if answer == "close" {
            std::process::exit(0);
        }
        // "again": loop back and restart the program.
    }
}
