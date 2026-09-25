//! phosphor-fleet-poll -- the fleet poller, standalone.
//!
//! Does exactly what lib/fleet.py's collect()/poller()/update_host()/_alert()
//! do: ssh collect.sh to every host, debounce a blip into a real transition,
//! call `phosphor notify` on one, and write fleet.json -- the same file
//! read_state() (and glance, and the adjutant) already read, so nothing on
//! the Python side has to know or care which process wrote it.
//!
//! Not wired into anything yet: `phosphor fleet` falls back to its own
//! Python poller thread whenever this binary isn't present, so nothing
//! breaks for an install without a Rust toolchain. See CHANGELOG.md.
//!
//! `[deck] demo = true` is refused on purpose: phosphor demo's fabricated,
//! drifting readings stay Python-only, never duplicated here.

use std::collections::HashMap;
use std::io::Write;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const COLLECT_SH: &str = include_str!("../../../share/collect.sh");
const INTERVAL: Duration = Duration::from_secs(15);
const SLOW_POLL_MS: i64 = 3000;
const CONNECT_TIMEOUT_S: u32 = 6;
const POLL_TIMEOUT: Duration = Duration::from_secs(25);
// A host that's missed DOWN_AFTER polls in a row doesn't need the full
// patience window on every single round just to confirm what every recent
// poll already found: still down. Matches lib/fleet.py's own numbers.
const DOWN_AFTER: u32 = 2;
const CONNECT_TIMEOUT_DOWN_S: u32 = 2;
const POLL_TIMEOUT_DOWN: Duration = Duration::from_secs(5);
const ALERT_COOLDOWN: Duration = Duration::from_secs(60);
const LOG_CAP: u64 = 200 * 1024;

struct Host {
    name: String,
    target: Option<String>, // None: this machine
}

fn home() -> String {
    std::env::var("HOME").unwrap_or_else(|_| "/".to_string())
}

fn profile_path() -> String {
    std::env::var("PHOSPHOR_PROFILE").unwrap_or_else(|_| format!("{}/.config/phosphor/deck.toml", home()))
}

fn cache_dir() -> String {
    std::env::var("PHOSPHOR_CACHE").unwrap_or_else(|_| format!("{}/.cache/phosphor", home()))
}

/// role -> sort weight, mirroring deckconf.ORDER; an unknown/missing role is 9.
fn role_order(role: Option<&str>) -> i32 {
    match role {
        Some("brain") => 0,
        Some("work") => 1,
        Some("desktop") => 2,
        Some("storage") => 3,
        Some("node") => 4,
        Some("viewer") => 5,
        _ => 9,
    }
}

/// deckconf.hosts() + deckconf.fleet_hosts(): brain-first ordering, viewers
/// and `fleet = false` hosts skipped, ssh target resolved the same way
/// (deckconf.target: ssh alias, else ip, else the name itself).
fn fleet_hosts(prof: &toml::Value) -> Option<Vec<Host>> {
    let deck = prof.get("deck")?;
    if deck.get("demo").and_then(|v| v.as_bool()).unwrap_or(false) {
        return None; // demo stays Python-only, on purpose
    }
    let mut hosts: Vec<&toml::Value> = prof.get("hosts").and_then(|v| v.as_array())
        .map(|a| a.iter().collect()).unwrap_or_default();
    hosts.sort_by_key(|h| {
        let role = h.get("role").and_then(|v| v.as_str());
        let name = h.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
        (role_order(role), name)
    });
    let mut out = Vec::new();
    for h in hosts {
        if h.get("fleet").and_then(|v| v.as_bool()) == Some(false) {
            continue;
        }
        let name = match h.get("name").and_then(|v| v.as_str()) {
            Some(n) => n.to_string(),
            None => continue,
        };
        let local = h.get("local").and_then(|v| v.as_bool()).unwrap_or(false);
        let role = h.get("role").and_then(|v| v.as_str());
        if local {
            out.push(Host { name, target: None });
        } else if role != Some("viewer") {
            let t = h.get("ssh").and_then(|v| v.as_str())
                .or_else(|| h.get("ip").and_then(|v| v.as_str()))
                .unwrap_or(&name);
            let target = match h.get("user").and_then(|v| v.as_str()) {
                Some(u) => format!("{}@{}", u, t),
                None => t.to_string(),
            };
            out.push(Host { name, target: Some(target) });
        }
    }
    Some(out)
}

fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_millis() as i64
}

fn stamp() -> String {
    // deck.log's own format ("%Y-%m-%d %H:%M:%S", local time), without pulling
    // in a chrono dependency for one line: `date` is on every machine this runs on.
    let out = Command::new("date").arg("+%Y-%m-%d %H:%M:%S").output();
    out.ok().and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "0000-00-00 00:00:00".to_string())
}

/// dlog.event(): one line, appended, size-capped -- same shape and same cap
/// as lib/dlog.py, so `phosphor logs fleet` reads either writer's lines back
/// exactly the same way. Never a host name (see the module docs and the
/// FLEET card instead): deck.log is meant to be safe to paste into an issue.
fn dlog_event(tool: &str, what: &str, detail: &str) {
    let dir = cache_dir();
    let _ = std::fs::create_dir_all(&dir);
    let path = format!("{}/deck.log", dir);
    let mut line = format!("{}  {:<10} {:<6}", stamp(), tool, what);
    if !detail.is_empty() {
        line.push(' ');
        line.push_str(detail);
    }
    line.push('\n');
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(&path) {
        let _ = f.write_all(line.as_bytes());
    }
    if let Ok(meta) = std::fs::metadata(&path) {
        if meta.len() > LOG_CAP {
            if let Ok(text) = std::fs::read_to_string(&path) {
                let lines: Vec<&str> = text.lines().collect();
                let half = lines[lines.len() / 2..].join("\n") + "\n";
                let _ = std::fs::write(&path, half);
            }
        }
    }
}

/// One collect.sh run, over ssh or local `sh -s`, with a hard wall-clock
/// timeout (no wait_timeout dependency: poll try_wait, kill past the limit --
/// same ceiling as lib/fleet.py's `subprocess.run(..., timeout=25)`).
/// `known_down`: this host has already missed DOWN_AFTER polls in a row --
/// a short probe instead of the full window (see lib/fleet.py's collect()
/// for why).
fn collect(target: &Option<String>, known_down: bool) -> (serde_json::Value, i64) {
    let t0 = Instant::now();
    let connect_t = if known_down { CONNECT_TIMEOUT_DOWN_S } else { CONNECT_TIMEOUT_S };
    let poll_timeout = if known_down { POLL_TIMEOUT_DOWN } else { POLL_TIMEOUT };
    let mut cmd = match target {
        None => {
            let mut c = Command::new("sh");
            c.arg("-s");
            c
        }
        Some(t) => {
            let mut c = Command::new("ssh");
            c.args(["-o", "BatchMode=yes", "-o"])
                .arg(format!("ConnectTimeout={}", connect_t))
                .arg(t)
                .arg("sh -s");
            c
        }
    };
    cmd.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = match cmd.spawn() {
        Ok(c) => c,
        Err(e) => return (fail(&e.to_string()), ms_since(t0)),
    };
    if let Some(mut stdin) = child.stdin.take() {
        let _ = stdin.write_all(COLLECT_SH.as_bytes());
    }
    let deadline = Instant::now() + poll_timeout;
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return (fail("timeout"), ms_since(t0));
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => return (fail(&e.to_string()), ms_since(t0)),
        }
    }
    let out = match child.wait_with_output() {
        Ok(o) => o,
        Err(e) => return (fail(&e.to_string()), ms_since(t0)),
    };
    let stdout = String::from_utf8_lossy(&out.stdout);
    if stdout.trim().is_empty() {
        let stderr = String::from_utf8_lossy(&out.stderr);
        let last = stderr.trim().lines().last().unwrap_or("no answer");
        return (fail(&last.chars().take(24).collect::<String>()), ms_since(t0));
    }
    (parse(&stdout), ms_since(t0))
}

fn ms_since(t0: Instant) -> i64 {
    t0.elapsed().as_millis() as i64
}

fn fail(err: &str) -> serde_json::Value {
    serde_json::json!({"ok": false, "err": err})
}

/// KEY=VALUE lines -> the same shape lib/fleet.py's collect() builds.
fn parse(stdout: &str) -> serde_json::Value {
    let mut d = serde_json::Map::new();
    d.insert("ok".into(), serde_json::json!(true));
    let mut mnt = Vec::new();
    let mut gpu = Vec::new();
    let mut ctr: Option<serde_json::Value> = None;
    for line in stdout.lines() {
        let Some((k, v)) = line.split_once('=') else { continue };
        match k {
            "MNT" => {
                let f: Vec<&str> = v.splitn(3, '|').collect();
                if f.len() == 3 {
                    mnt.push(serde_json::json!([f[0], f[1].parse::<i64>().unwrap_or(0), f[2]]));
                }
            }
            "GPU" => {
                let f: Vec<&str> = v.split('|').collect();
                let get = |i: usize| f.get(i).copied().unwrap_or("");
                gpu.push(serde_json::json!({
                    "name": get(0), "util": get(1), "used": get(2), "total": get(3), "temp": get(4)
                }));
            }
            "CTR" => {
                let f: Vec<&str> = v.splitn(3, '|').collect();
                if f.len() == 3 {
                    ctr = Some(serde_json::json!([f[0], f[1].parse::<i64>().unwrap_or(0),
                                                   f[2].parse::<i64>().unwrap_or(0)]));
                }
            }
            "CPU" | "MEMU" | "MEMT" | "SVCFAIL" => {
                d.insert(k.into(), serde_json::json!(v.parse::<i64>().unwrap_or(0)));
            }
            _ => {
                d.insert(k.into(), serde_json::json!(v));
            }
        }
    }
    d.insert("mnt".into(), serde_json::Value::Array(mnt));
    d.insert("gpu".into(), serde_json::Value::Array(gpu));
    d.insert("ctr".into(), ctr.unwrap_or(serde_json::Value::Null));
    serde_json::Value::Object(d)
}

/// `phosphor notify --tab SYS --fleet-alert TEXT`, off the polling path
/// (fire and forget, same as lib/fleet.py's `_alert`'s own thread). SYS,
/// not FLEET: the fleet card lives inside the SYS tab, alongside pulse and
/// the adjutant -- no tab is ever named "FLEET" (see the Python fix,
/// commit 7d5f022: a --tab naming a tab that doesn't exist marks nothing
/// and can never be cleared either).
fn notify_args(text: &str) -> [&str; 5] {
    ["notify", "--tab", "SYS", "--fleet-alert", text]
}

fn notify(text: &str) {
    let phosphor = format!("{}/.local/bin/phosphor", home());
    let bin = if std::path::Path::new(&phosphor).exists() { phosphor } else { "phosphor".to_string() };
    let _ = Command::new(bin)
        .args(notify_args(text))
        .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
        .spawn();
}

fn write_cache(hosts_state: &HashMap<String, serde_json::Value>) {
    let dir = cache_dir();
    let _ = std::fs::create_dir_all(&dir);
    let path = format!("{}/fleet.json", dir);
    let tmp = format!("{}.tmp", path);
    let doc = serde_json::json!({"t": now_ms() as f64 / 1000.0, "hosts": hosts_state});
    if std::fs::write(&tmp, doc.to_string()).is_ok() {
        let _ = std::fs::rename(&tmp, &path);
    }
}

fn main() {
    let text = match std::fs::read_to_string(profile_path()) {
        Ok(t) => t,
        Err(_) => return,
    };
    let prof: toml::Value = match toml::from_str(&text) {
        Ok(p) => p,
        Err(_) => return,
    };
    let hosts = match fleet_hosts(&prof) {
        Some(h) if !h.is_empty() => h,
        _ => return, // no hosts, or demo=true: nothing for this binary to do
    };

    let mut state: HashMap<String, serde_json::Value> = HashMap::new();
    let mut fails: HashMap<String, u32> = HashMap::new();
    let mut prev_ok: HashMap<String, bool> = HashMap::new();
    let mut prev_svcfail: HashMap<String, i64> = HashMap::new();
    let mut last_alert: HashMap<String, Instant> = HashMap::new();
    let mut throttled: HashMap<&str, Instant> = HashMap::new();
    let mut first = true;

    loop {
        let t0 = Instant::now();
        let results: Vec<(String, serde_json::Value, i64)> = std::thread::scope(|scope| {
            let handles: Vec<_> = hosts.iter().map(|h| {
                let target = h.target.clone();
                let name = h.name.clone();
                let known_down = fails.get(&name).copied().unwrap_or(0) >= DOWN_AFTER;
                scope.spawn(move || {
                    let (mut r, ms) = collect(&target, known_down);
                    r.as_object_mut().unwrap().insert("ms".into(), serde_json::json!(ms));
                    (name, r, ms)
                })
            }).collect();
            handles.into_iter().map(|h| h.join().unwrap()).collect()
        });

        for (name, r, _ms) in results {
            let ok = r.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            let f = fails.entry(name.clone()).or_insert(0);
            if !ok {
                *f += 1;
                let was_ok_before = state.get(&name).and_then(|s| s.get("ok")).and_then(|v| v.as_bool()).unwrap_or(false);
                if *f < 2 && was_ok_before {
                    continue; // one blip isn't an outage: keep the last good reading
                }
            } else {
                *f = 0;
            }
            let now_ok = ok;
            if let Some(&was) = prev_ok.get(&name) {
                if was != now_ok {
                    let cooled = last_alert.get(&name).map(|t| t.elapsed() >= ALERT_COOLDOWN).unwrap_or(true);
                    if cooled {
                        last_alert.insert(name.clone(), Instant::now());
                        let text = if now_ok { format!("{} is back", name) } else { format!("{} is unreachable", name) };
                        notify(&text);
                    }
                }
            }
            prev_ok.insert(name.clone(), now_ok);
            // A service crashing is a more common self-hosting failure than
            // the whole host going down -- same first-poll and cooldown rules
            // as the host up/down alert above (1:1 with lib/fleet.py's
            // update_host()).
            if now_ok {
                let svcfail = r.get("SVCFAIL").and_then(|v| v.as_i64()).unwrap_or(0);
                if let Some(&was) = prev_svcfail.get(&name) {
                    if was != svcfail {
                        let cooled = last_alert.get(&name).map(|t| t.elapsed() >= ALERT_COOLDOWN).unwrap_or(true);
                        if cooled {
                            if svcfail > 0 && was == 0 {
                                last_alert.insert(name.clone(), Instant::now());
                                let unit = if svcfail == 1 { "service" } else { "services" };
                                notify(&format!("{}: {} {} failed", name, svcfail, unit));
                            } else if svcfail == 0 && was > 0 {
                                last_alert.insert(name.clone(), Instant::now());
                                notify(&format!("{}: services back to normal", name));
                            }
                        }
                    }
                }
                prev_svcfail.insert(name.clone(), svcfail);
            }
            state.insert(name, r);
        }

        let round_ms = t0.elapsed().as_millis() as i64;
        if first {
            dlog_event("FLEET", "first-poll", &format!("{}ms, {} hosts", round_ms, hosts.len()));
            first = false;
        } else if round_ms > SLOW_POLL_MS {
            let key = "slow-round";
            let due = throttled.get(key).map(|t| t.elapsed() >= Duration::from_secs(120)).unwrap_or(true);
            if due {
                throttled.insert(key, Instant::now());
                dlog_event("FLEET", "slow-round", &format!("{}ms", round_ms));
            }
        }

        write_cache(&state);
        std::thread::sleep(INTERVAL);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_every_collect_sh_key() {
        let out = "CPU=7\nMEMU=5855\nMEMT=12904\nLOAD=2.26 1.50 1.19\nUP=16h\n\
                    SVCFAIL=2\nREBOOT=1\n\
                    MNT=/|63|467G\nMNT=/mnt/data|53|1.9T\n\
                    GPU=AMD|38|4200|12288|57\nCTR=docker|7|0\n";
        let d = parse(out);
        assert_eq!(d["ok"], serde_json::json!(true));
        assert_eq!(d["CPU"], serde_json::json!(7));
        assert_eq!(d["MEMU"], serde_json::json!(5855));
        assert_eq!(d["UP"], serde_json::json!("16h"));
        assert_eq!(d["SVCFAIL"], serde_json::json!(2), "a number, like CPU/MEMU/MEMT, not a string");
        assert_eq!(d["REBOOT"], serde_json::json!("1"));
        assert_eq!(d["mnt"], serde_json::json!([["/", 63, "467G"], ["/mnt/data", 53, "1.9T"]]));
        assert_eq!(d["gpu"][0]["name"], serde_json::json!("AMD"));
        assert_eq!(d["ctr"], serde_json::json!(["docker", 7, 0]));
    }

    #[test]
    fn no_svcfail_line_means_no_failures() {
        let d = parse("CPU=7\n");
        assert!(d.get("SVCFAIL").is_none());
    }

    #[test]
    fn alert_marks_the_real_sys_tab_not_a_made_up_fleet_one() {
        assert_eq!(notify_args("db-box is unreachable"),
                   ["notify", "--tab", "SYS", "--fleet-alert", "db-box is unreachable"]);
    }

    #[test]
    fn known_down_timeouts_are_real_and_shorter() {
        assert!(CONNECT_TIMEOUT_DOWN_S < CONNECT_TIMEOUT_S);
        assert!(POLL_TIMEOUT_DOWN < POLL_TIMEOUT);
    }

    #[test]
    fn collect_local_still_succeeds_under_the_tighter_known_down_deadline() {
        // The local `sh -s` path (collect.sh's own ~0.4s CPU sample) has no
        // ssh connect step at all, so know_down's shorter 5s poll timeout
        // should never be a real constraint -- if it ever became one, this
        // catches it instead of a live deck quietly missing local readings.
        let (d, _ms) = collect(&None, true);
        assert_eq!(d["ok"], serde_json::json!(true));
        let (d, _ms) = collect(&None, false);
        assert_eq!(d["ok"], serde_json::json!(true));
    }

    #[test]
    fn parse_never_panics_on_a_garbled_line() {
        let d = parse("CPU=notanumber\nno-equals-sign-here\n=emptykey\n");
        // CPU parses as 0 (unwrap_or(0)), never a crash -- a flaky host
        // sending a half-written line must not take the whole poller down.
        assert_eq!(d["CPU"], serde_json::json!(0));
    }

    #[test]
    fn role_order_matches_deckconf_order() {
        assert_eq!(role_order(Some("brain")), 0);
        assert_eq!(role_order(Some("viewer")), 5);
        assert_eq!(role_order(None), 9); // missing role sorts last, not as "viewer"
        assert_eq!(role_order(Some("something-unknown")), 9);
    }

    fn toml_of(s: &str) -> toml::Value {
        toml::from_str(s).unwrap()
    }

    #[test]
    fn fleet_hosts_orders_brain_first_and_resolves_targets() {
        let prof = toml_of(r#"
            [deck]
            [[hosts]]
            name = "b-node"
            role = "node"
            [[hosts]]
            name = "a-brain"
            role = "brain"
            local = true
            [[hosts]]
            name = "c-work"
            role = "work"
            ssh = "work-alias"
            user = "alice"
        "#);
        let hosts = fleet_hosts(&prof).unwrap();
        let names: Vec<&str> = hosts.iter().map(|h| h.name.as_str()).collect();
        assert_eq!(names, vec!["a-brain", "c-work", "b-node"]); // brain, then work, then node
        assert_eq!(hosts[0].target, None); // local
        assert_eq!(hosts[1].target.as_deref(), Some("alice@work-alias")); // ssh alias + user
    }

    #[test]
    fn fleet_hosts_skips_viewers_and_fleet_false() {
        let prof = toml_of(r#"
            [deck]
            [[hosts]]
            name = "phone"
            role = "viewer"
            [[hosts]]
            name = "off-panel"
            role = "node"
            fleet = false
            [[hosts]]
            name = "brain"
            role = "brain"
            local = true
        "#);
        let hosts = fleet_hosts(&prof).unwrap();
        let names: Vec<&str> = hosts.iter().map(|h| h.name.as_str()).collect();
        assert_eq!(names, vec!["brain"]);
    }

    #[test]
    fn demo_mode_returns_nothing_to_poll() {
        let prof = toml_of(r#"
            [deck]
            demo = true
            [[hosts]]
            name = "brain"
            role = "brain"
            local = true
        "#);
        assert!(fleet_hosts(&prof).is_none());
    }

    #[test]
    fn dlog_line_never_carries_a_host_name_and_parses_like_tail_for() {
        let dir = std::env::temp_dir().join(format!("fleet-poll-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        std::env::set_var("PHOSPHOR_CACHE", &dir);
        dlog_event("FLEET", "first-poll", "42ms, 3 hosts");
        let text = std::fs::read_to_string(dir.join("deck.log")).unwrap();
        let line = text.lines().next().unwrap();
        // Python's dlog.tail_for() does line.split(None, 3): whitespace-collapsing,
        // so the tool name is the 3rd token regardless of the padding here.
        let tokens: Vec<&str> = line.split_whitespace().collect();
        assert_eq!(tokens[2], "FLEET");
        assert!(tokens.contains(&"first-poll"));
        assert!(!line.contains("nowhere") && !line.contains("hostname"));
        std::fs::remove_dir_all(&dir).ok();
    }
}
