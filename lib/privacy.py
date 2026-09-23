"""phosphor privacy - before you push: finds your own data in what git would
publish. Project Phosphor Deck.

What counts as yours is read from your own setup, never written here: the
host names, IPs, users and ssh aliases in your profile, your git email, your
user and home, tailscale addresses, your headscale server, and your
matterhorn server and login.

  phosphor privacy            scan what's staged/tracked (the git index)
  phosphor privacy --hook     same, quiet unless something turns up (pre-commit)
  phosphor privacy --install  add it as this repo's pre-commit hook

IPs, users, emails and servers block (exit 1). Host names only warn: they
are often ordinary words ("homelab") that also show up in examples.

A host name meant as an example goes in .privacy-allow at the repo's top,
with the files it may appear in, and stops warning there (anywhere else it
still does). Nothing that blocks can be allowed:

    homelab   profiles/example.toml README.md
"""
import configparser, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

TAILSCALE = re.compile(r"\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d{1,3}\.\d{1,3}\b")
# The copyright line of a license is meant to carry a name.
SKIP = {"LICENSE"}
# Too generic to mean anything on their own.
GENERIC = {"root", "user", "admin", "pi", "ubuntu", "debian", "home", "localhost"}

def git(*a):
    try:
        # errors="replace": a binary file (an image, say) isn't valid UTF-8,
        # and a crash here would block a commit `phosphor privacy` should
        # just wave through -- there's no text in it to find anyway.
        return subprocess.run(["git"] + list(a), capture_output=True, text=True, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(a, 1, "", "git not found")

def tokens():
    """{token: (kind, hard)} gathered from this user's own setup."""
    T = {}
    def put(v, kind, hard):
        v = (v or "").strip()
        if len(v) >= 3 and v.lower() not in GENERIC:
            T.setdefault(v, (kind, hard))
    if os.path.exists(deckconf.CONF):
        prof, _ = deckconf.load()
        for h in (prof or {}).get("hosts", []):
            put(h.get("ip"), "ip in your profile", True)
            put(h.get("user"), "user in your profile", True)
            put(h.get("name"), "host name", False)
            put(h.get("ssh"), "ssh alias", False)
    put(git("config", "user.email").stdout, "your git email", True)
    user = os.environ.get("USER", "")
    put(user, "your user", True)
    home = os.path.expanduser("~")
    if home not in ("/root", "/"):
        put(home, "your home path", True)
    try:
        import mesh
        from urllib.parse import urlparse
        kind, url = mesh.detect()
        if kind == "headscale" and url:
            put(urlparse(url).hostname, "your headscale server", True)
    except Exception as e:
        import dlog
        dlog.event("PRIVACY", "mesh-detect-failed", str(e)[:60])
    ini = os.path.expanduser("~/.config/matterhorn/config.ini")
    if os.path.exists(ini):
        c = configparser.ConfigParser()
        try:
            c.read(ini)
            m = c["mattermost"]
            put(m.get("host"), "your Mattermost server", True)
            put(m.get("user"), "your Mattermost login", True)
        except Exception:
            import dlog
            # never the exception text: a parse error can quote the bad line,
            # and that line is exactly the host/login this scan exists to protect
            dlog.event("PRIVACY", "matterhorn-config-failed")
    return T

ALLOW = ".privacy-allow"

def allowed():
    """{word (lowercase): {files}} from the index's .privacy-allow."""
    out = {}
    for line in git("show", ":" + ALLOW).stdout.splitlines():
        words = line.split("#", 1)[0].split()
        if len(words) >= 2:
            out.setdefault(words[0].lower(), set()).update(words[1:])
    return out

def scan():
    """[(file, line, kind, hard, shown)] over the git index, and how many
    host names .privacy-allow let through."""
    files = [f for f in git("ls-files").stdout.splitlines() if f not in SKIP and f != ALLOW]
    ok = allowed()
    T = tokens()
    pats = [(re.compile(r"(?<![\w.-])" + re.escape(t) + r"(?![\w-])", re.I), t, k, h)
            for t, (k, h) in T.items()]
    out, let = [], 0
    for f in files:
        blob = git("show", ":" + f).stdout
        for n, line in enumerate(blob.splitlines(), 1):
            for rx, t, k, h in pats:
                if rx.search(line):
                    if not h and f in ok.get(t.lower(), ()):
                        let += 1; continue
                    out.append((f, n, k, h, t))
            for m in TAILSCALE.finditer(line):
                if m.group(0) not in T and not m.group(0).startswith("100.64.0.0"):
                    out.append((f, n, "a tailscale address", True, m.group(0)))
    return out, let

def install():
    top = git("rev-parse", "--show-toplevel").stdout.strip()
    if not top:
        print("  not inside a git repo"); return 1
    hook = os.path.join(top, ".git", "hooks", "pre-commit")
    body = ('#!/bin/sh\n# added by `phosphor privacy --install`\n'
            'exec python3 "%s" privacy --hook\n' % os.path.join(REPO, "phosphor"))
    if os.path.exists(hook) and "phosphor privacy" not in open(hook).read():
        print(row(WARN, "pre-commit", "there's already a hook", note="add the line by hand"))
        return 1
    open(hook, "w").write(body); os.chmod(hook, 0o755)
    print(row(OK, "pre-commit", hook)); return 0

def main():
    args = sys.argv[1:]
    if "--install" in args:
        return install()
    quiet = "--hook" in args
    if not git("rev-parse", "--git-dir").stdout.strip():
        print("  run it inside the repo you're about to push"); return 1
    found, let = scan()
    hard = [x for x in found if x[3]]
    if quiet and not found:
        return 0
    print()
    print(BLOOM + "  phosphor privacy" + RST + DIM + "   what git would publish" + RST)
    if not found:
        print(row(OK, "clean", "nothing of yours in the tracked files",
                  note=("%d example(s) allowed in %s" % (let, ALLOW)) if let else ""))
        print(); return 0
    for f, n, k, h, t in found:
        print(row(BAD if h else WARN, "%s:%d" % (f, n), k, note=t))
    print()
    if hard:
        print("  " + RED + "%d finding(s) that must go before this is public." % len(hard) + RST)
        if quiet:
            print("  " + DIM + "commit anyway: git commit --no-verify" + RST)
    else:
        print("  " + AMB + "only host names: check they're meant as examples." + RST)
        print("  " + DIM + "an example on purpose: add it to %s with its files" % ALLOW + RST)
    print()
    return 1 if hard else 0

if __name__ == "__main__":
    sys.exit(main() or 0)
