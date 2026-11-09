#!/usr/bin/env python3
"""A screen's `deck` reconnects when the link drops -- but only while it
still has a terminal. A phone's `deck` whose window was gone (the link
dropped as the phone switched networks) kept knocking on the brain every few
seconds, forever: each try reached the live session and every screen on it
flickered. Every `deck` a screen gets (the phone kit's, the other-screen
kit's, the one `phosphor gen` writes on a viewer) has to:

- with no terminal, try once and stop;
- with one, keep reconnecting until ssh comes back clean (a detach).

    python3 tests/deck-loop-check.py
"""
import os, pty, shutil, subprocess, sys, tempfile
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import gen, phone

fails = []
def check(what, ok, detail=""):
    if not ok: fails.append(what + (": " + detail[-300:] if detail else ""))

def stub(d, name, body):
    p = os.path.join(d, name)
    open(p, "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(p, 0o755)

def kit_deck(kit, termux, d):
    """Run a kit (its ssh stubbed: the key works) and return the deck it wrote."""
    home, bin_ = os.path.join(d, "home"), os.path.join(d, "kitstubs")
    os.makedirs(os.path.join(home, ".ssh")); os.makedirs(bin_)
    open(os.path.join(home, ".ssh/id_ed25519"), "w").write("key\n")
    stub(bin_, "ssh", 'case " $* " in *" -n "*) ;; *) cat >/dev/null ;; esac\nexit 0')
    stub(bin_, "termux-reload-settings", "exit 0")
    env = {"HOME": home, "PATH": bin_ + ":/usr/bin:/bin"}
    if termux:
        root = os.path.join(d, "termux")
        env["PREFIX"] = os.path.join(root, "files/usr")
        os.makedirs(os.path.join(env["PREFIX"], "bin"))
        kit = kit.replace("/data/data/com.termux", root)
        deck = os.path.join(env["PREFIX"], "bin/deck")
    else:
        deck = os.path.join(home, ".local/bin/deck")
    subprocess.run(["sh"], input=kit, env=env, cwd=d, capture_output=True, text=True, timeout=60)
    text = open(deck).read()
    return "#!/bin/sh\n" + text.split("\n", 1)[1]    # its #! is Termux's sh

def loop_env(d, drops):
    """ssh drops the link `drops` times (exit 255), then comes back clean;
    clipsync's own ssh is left out of the count. sleep doesn't wait."""
    bin_ = os.path.join(d, "loopstubs"); os.makedirs(bin_, exist_ok=True)
    count = os.path.join(d, "ssh-calls")
    open(count, "w").close()
    stub(bin_, "ssh", 'case " $* " in *clipsync*) exit 1 ;; esac\n'
                      'echo x >> "%s"\n'
                      '[ "$(wc -l < "%s")" -gt %d ] && exit 0\nexit 255' % (count, count, drops))
    stub(bin_, "sleep", "exit 0")
    env = {"HOME": os.path.join(d, "home"), "PATH": bin_ + ":/usr/bin:/bin"}
    return env, count

def calls(count):
    return len(open(count).read().split())

def run_deck(name, text):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "home"), exist_ok=True)
    deck = os.path.join(d, "deck")
    open(deck, "w").write(text); os.chmod(deck, 0o755)

    # no terminal: one try, then it stops
    env, count = loop_env(d, drops=1000)
    try:
        r = subprocess.run([deck], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           env=env, timeout=20)
        check("%s, no terminal: it stops after one try (ssh ran %d times)" % (name, calls(count)),
              calls(count) == 1 and r.returncode != 0, r.stdout + r.stderr)
        check("%s, no terminal: it says why" % name, "no terminal left" in r.stdout, r.stdout)
    except subprocess.TimeoutExpired:
        check("%s, no terminal: it stops (it kept reconnecting, ssh ran %d times)"
              % (name, calls(count)), False)

    # a terminal: it reconnects through two drops, then a detach ends it
    env, count = loop_env(d, drops=2)
    master, slave = pty.openpty()
    try:
        p = subprocess.Popen([deck], stdin=slave, stdout=slave, stderr=slave, env=env)
        os.close(slave)
        rc = p.wait(timeout=20)
        check("%s, a terminal: it reconnects until a clean exit (ssh ran %d times, rc %d)"
              % (name, calls(count), rc), calls(count) == 3 and rc == 0)
    except subprocess.TimeoutExpired:
        p.kill()
        check("%s, a terminal: it ends on a clean exit" % name, False)
    finally:
        os.close(master)
    shutil.rmtree(d)

prof = {"hosts": [{"name": "nimbus", "role": "brain", "user": "you"}]}
d = tempfile.mkdtemp()
run_deck("the phone kit's deck", kit_deck(phone.script(prof, "phone"), True, os.path.join(d, "a")))
run_deck("the screen kit's deck", kit_deck(phone.screen_script(prof), False, os.path.join(d, "b")))
shutil.rmtree(d)
vals = {"target": "you@nimbus", "command": "~/.local/bin/deck", "session": "deck", "clip": ""}
run_deck("gen's viewer deck", gen.CONNECT % {"brain": "nimbus", "body": gen.CONNECT_SSH % vals})

if fails:
    for f in fails: print("FAIL:", f)
    sys.exit(1)
print("ok: a screen's deck reconnects only while it has a terminal")
