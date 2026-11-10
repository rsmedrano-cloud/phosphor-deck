#!/usr/bin/env python3
"""A kit runs piped into sh (`ssh brain 'phosphor phone' | sh`), so the
rest of the kit is sh's stdin -- and any command in it that reads stdin
eats the kit. ssh does: the "does the key work yet" probe, run again on a
screen whose key already works, swallowed everything after it and the kit
ended silently, the deck command never rewritten. Each kit, piped into sh
on a screen whose key works, has to reach its end and write `deck`.

And the other way round: a link that drops halfway delivers half a kit
(a phone once got 429 bytes), and sh runs each line as it comes. A kit cut
anywhere short of its end has to run none of itself. So does install.sh,
the one `curl ... | sh` a newcomer runs first.

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

def cut(name, kit, termux, sh):
    """every prefix of the kit, fed to sh: nothing runs, nothing is written"""
    d = tempfile.mkdtemp()
    home, bin_, log = os.path.join(d, "home"), os.path.join(d, "stubs"), os.path.join(d, "ran")
    os.makedirs(os.path.join(home, ".ssh")); os.makedirs(bin_)
    open(os.path.join(home, ".ssh/id_ed25519"), "w").write("key\n")
    for stub in ("ssh", "ssh-keygen", "ssh-copy-id", "pkg", "termux-reload-settings", "mkdir", "chmod", "mv", "cat",
                 "curl", "wget", "git", "tar", "rsync", "cp", "ln", "rm", "uname", "mktemp", "dirname", "id"):
        p = os.path.join(bin_, stub)
        open(p, "w").write('#!/bin/sh\necho "%s $*" >> %s\n' % (stub, log)); os.chmod(p, 0o755)
    env = {"HOME": home, "PATH": bin_}
    if termux:
        env["PREFIX"] = os.path.join(d, "termux/files/usr")
        kit = kit.replace("/data/data/com.termux", os.path.join(d, "termux"))
    before = sorted(os.walk(home))
    step = max(1, len(kit) // 60)
    for n in list(range(1, len(kit) - 1, step)) + [len(kit) - 2]:   # -2: the call's own newline counts as whole
        r = subprocess.run([sh], input=kit[:n], capture_output=True, text=True, env=env, cwd=d, timeout=20)
        ran = open(log).read() if os.path.exists(log) else ""
        what = "%s cut at byte %d of %d, piped into %s" % (name, n, len(kit), os.path.basename(sh))
        check("%s: it ran %r / said %r" % (what, ran[:120], r.stdout[:120]),
              not ran and not r.stdout and sorted(os.walk(home)) == before)
        if os.path.exists(log): os.remove(log)
    shutil.rmtree(d)

prof = {"hosts": [{"name": "nimbus", "role": "brain", "user": "you"}]}
for sh in filter(None, (shutil.which("sh"), shutil.which("bash"))):
    run("the phone kit", phone.script(prof, "phone"), True, sh)
    run("the screen kit", phone.screen_script(prof), False, sh)
    cut("the phone kit", phone.script(prof, "phone"), True, sh)
    cut("the screen kit", phone.screen_script(prof), False, sh)
    cut("install.sh", open(os.path.join(REPO, "install.sh")).read(), False, sh)

if fails:
    for f in fails: print("FAIL:", f)
    sys.exit(1)
print("ok: a kit run again reaches its end and rewrites deck; a kit or install.sh cut short runs nothing")
