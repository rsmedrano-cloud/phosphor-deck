#!/usr/bin/env python3
"""phosphor demo - a throwaway session over made-up machines, safe for a
screenshot or a recording: never your real profile, never your real
session, never a real IP, hostname or note.

    phosphor demo            build it (if needed) and get in
    phosphor demo --stop     kill it and clean up

Runs from profiles/demo.toml instead of your profile (PHOSPHOR_PROFILE for
every pane it opens) and profiles/demo-tabs.d instead of your tabs.d, so
nothing of yours leaks in. It writes no systemd unit and touches no mount:
just a zellij session of its own (`phosphor-demo` by default). Its notebook, chat
feed, events, fleet readings and log live in ~/.cache/phosphor/demo-state, never in
the machine's real ones. What it can't hide is the machine's own user and host name
(paths, prompts): for a public screenshot use a machine whose user name you'd show.
"""
import os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import DIM, RST
import deckconf

PROFILE  = os.path.join(deckconf.REPO, "profiles", "demo.toml")
TEMPLATE = os.path.join(deckconf.REPO, "profiles", "demo-notes.md")
TABS_D   = os.path.join(deckconf.REPO, "profiles", "demo-tabs.d")
LAYOUT   = os.path.expanduser("~/.cache/phosphor/demo.kdl")
# everything the demo reads or writes at run time lives under here, never in the real
# ~/.local/share/phosphor or ~/.cache/phosphor: mentions, the adjutant's events, the fleet's
# readings, the log. (A demo that showed this machine's real chat feed leaked a name.)
STATE    = os.path.expanduser("~/.cache/phosphor/demo-state")


def load_profile():
    if deckconf.tomllib is None:
        print("no TOML parser: pip install --user tomli")
        return None
    with open(PROFILE, "rb") as f:
        return deckconf.tomllib.load(f)


def zellij_bin():
    zj = os.path.expanduser("~/.local/bin/zellij")
    return zj if os.path.exists(zj) else shutil.which("zellij")


def session_live(zj, sess):
    try:
        out = subprocess.run([zj, "list-sessions", "-n"], capture_output=True,
                             text=True, timeout=15).stdout
    except (subprocess.TimeoutExpired, OSError):
        return False
    return any(l.split()[:1] == [sess] and "EXITED" not in l for l in out.splitlines())


def seed_notes(folder):
    """A fixed, made-up notebook the first time -- never your real one."""
    folder = os.path.expanduser(folder)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, "notes.md")
    if not os.path.exists(dest) and os.path.exists(TEMPLATE):
        shutil.copy(TEMPLATE, dest)


def build_layout(prof):
    import gen
    ctx = gen.Ctx(prof)
    kdl = gen.deck_kdl(prof, ctx, "profiles/demo.toml (phosphor demo)")
    os.makedirs(os.path.dirname(LAYOUT), exist_ok=True)
    with open(LAYOUT, "w") as f:
        f.write(kdl)
    return LAYOUT


def background_env():
    """Env for the zellij subprocess that builds the demo session.

    Run from a pane inside your real deck and ZELLIJ/ZELLIJ_SESSION_NAME/
    ZELLIJ_PANE_ID leak in from the shell: zellij then reads
    ZELLIJ_SESSION_NAME as "the session you're already in" and appends the
    demo's tabs there instead of starting a session of its own -- your real
    deck, not a throwaway one."""
    env = dict(os.environ, PHOSPHOR_PROFILE=PROFILE, PHOSPHOR_TABS_D=TABS_D,
               PHOSPHOR_DATA=os.path.join(STATE, "data"), PHOSPHOR_CACHE=os.path.join(STATE, "cache"))
    for d in (env["PHOSPHOR_DATA"], env["PHOSPHOR_CACHE"]):
        os.makedirs(d, exist_ok=True)
    for leak in ("ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID"):
        env.pop(leak, None)
    return env


def stop(sess):
    zj = zellij_bin()
    if not zj:
        print("zellij isn't installed")
        return 1
    subprocess.run([zj, "kill-session", sess], capture_output=True)
    time.sleep(1)
    subprocess.run([zj, "delete-session", sess], capture_output=True)
    shutil.rmtree(STATE, ignore_errors=True)
    print("  %s stopped" % sess)
    return 0


def main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    prof = load_profile()
    if prof is None:
        return 1
    sess = ((prof.get("deck") or {}).get("session")) or "phosphor-demo"

    if argv and argv[0] == "--stop":
        return stop(sess)

    zj = zellij_bin()
    if not zj:
        print("  zellij isn't installed: run install.sh again (it fetches it)")
        return 1

    if not session_live(zj, sess):
        seed_notes(((prof.get("notes") or {}).get("folder")) or "~/.local/share/phosphor")
        layout = build_layout(prof)
        print("  building the demo deck...")
        r = subprocess.run([zj, "--layout", layout, "attach", "--create-background", sess],
                           env=background_env(), capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            print("  couldn't start the demo session: %s" % (r.stderr or r.stdout).strip()[:200])
            return 1
        time.sleep(2)

    print("  " + DIM + ("out: phosphor demo --stop" if os.environ.get("ZELLIJ")
                        else "leave with Alt-x, out for good: phosphor demo --stop") + RST)
    if os.environ.get("ZELLIJ"):
        print("  already inside a session: open another terminal and run "
              "`zellij attach %s` (or plain `phosphor demo` again)" % sess)
        return 0
    os.execv(zj, [zj, "attach", sess])


if __name__ == "__main__":
    sys.exit(main() or 0)
