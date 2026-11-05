#!/usr/bin/env python3
"""A kit runs piped into sh (`ssh brain 'phosphor phone' | sh`), so the
rest of the kit is sh's stdin -- and any command in it that reads stdin
eats the kit. ssh does: the "does the key work yet" probe, run again on a
screen whose key already works, swallowed everything after it and the kit
ended silently, the deck command never rewritten. Each kit, piped into sh
on a screen whose key works, has to reach its end and write `deck`.

    python3 tests/kit-rerun-check.py
"""
import os, shutil, subprocess, sys, tempfile, time
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))
import phone

fails = []
def check(what, ok):
    if not ok: fails.append(what)

def feed(sh, kit, env, cwd):
    """the kit as ssh delivers it: in pieces, not all there when sh starts"""
    p = subprocess.Popen([sh], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         env=env, cwd=cwd, text=True)
    for i in range(0, len(kit), 512):
        try:
            p.stdin.write(kit[i:i + 512]); p.stdin.flush()
        except BrokenPipeError:
            break
        time.sleep(0.05)
    try:
        p.stdin.close()
    except BrokenPipeError:
        pass
    out = p.stdout.read()
    return p.wait(timeout=30), out

def run(name, kit, termux, sh):
    d = tempfile.mkdtemp()
    home, bin_ = os.path.join(d, "home"), os.path.join(d, "stubs")
    os.makedirs(os.path.join(home, ".ssh")); os.makedirs(bin_)
    open(os.path.join(home, ".ssh/id_ed25519"), "w").write("key\n")
    # like the real one: reads its stdin unless -n, and the key works
    for stub, body in (("ssh", 'case " $* " in *" -n "*) ;; *) cat >/dev/null ;; esac\nexit 0\n'), ("termux-reload-settings", "exit 0\n")):
        p = os.path.join(bin_, stub)
        open(p, "w").write("#!/bin/sh\n" + body); os.chmod(p, 0o755)
    env = {"HOME": home, "PATH": bin_ + ":/usr/bin:/bin"}
    if termux:
        root = os.path.join(d, "termux")              # stands in for /data/data/com.termux
        env["PREFIX"] = os.path.join(root, "files/usr")
        os.makedirs(os.path.join(env["PREFIX"], "bin"))
        kit = kit.replace("/data/data/com.termux", root)
        deck = os.path.join(env["PREFIX"], "bin/deck")
    else:
        deck = os.path.join(home, ".local/bin/deck")
    rc, out = feed(sh, kit, env, d)
    name = "%s run again, piped into %s" % (name, os.path.basename(sh))
    check("%s: it reaches its end (got %r)" % (name, out[-300:]), rc == 0 and "done" in out)
    check("%s: it rewrites the deck command" % name, os.access(deck, os.X_OK))
    shutil.rmtree(d)

prof = {"hosts": [{"name": "nimbus", "role": "brain", "user": "you"}]}
for sh in filter(None, (shutil.which("sh"), shutil.which("bash"))):
    run("the phone kit", phone.script(prof, "phone"), True, sh)
    run("the screen kit", phone.screen_script(prof), False, sh)

if fails:
    for f in fails: print("FAIL:", f)
    sys.exit(1)
print("ok: a kit run again reaches its end and rewrites deck")
