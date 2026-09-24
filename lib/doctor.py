"""phosphor doctor - preflight. Every check here exists because something
broke before."""
import os, shutil, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

HOME = os.path.expanduser("~")
LOCALBIN = os.path.join(HOME, ".local/bin")

def sh(cmd, t=8):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return r.returncode, (r.stdout or r.stderr).strip()
    except Exception as e:
        return 1, str(e)

def have(b):
    p = os.path.join(LOCALBIN, b)
    if os.path.isfile(p) and os.access(p, os.X_OK): return p
    return shutil.which(b)

def run(profile=None):
    w = width()
    issues, blockers = [], []
    print()
    print(BLOOM + "  PHOSPHOR DECK · doctor" + RST)
    print(DIM + "  every check below exists because something broke before" + RST)

    print("\n" + rule("system", w))
    _, osname = sh(". /etc/os-release 2>/dev/null && echo $PRETTY_NAME")
    _, arch = sh("uname -m")
    print(row(OK, "os", "%s (%s)" % (osname or "?", arch)))
    print(row(OK, "python", "%d.%d" % sys.version_info[:2]))

    print("\n" + rule("PATH", w))
    inpath = LOCALBIN in os.environ.get("PATH", "").split(":")
    # a non-interactive shell doesn't read .bashrc: look at the rc files too
    declared = any(
        os.path.exists(os.path.expanduser(f)) and ".local/bin" in open(os.path.expanduser(f)).read()
        for f in ("~/.bashrc", "~/.profile", "~/.zshrc", "~/.bash_profile"))
    if inpath:
        print(row(OK, "~/.local/bin in PATH", "yes"))
    elif declared:
        print(row(OK, "~/.local/bin in PATH", "set in a shell rc",
                  note="missing in non-interactive shells"))
    else:
        print(row(WARN, "~/.local/bin in PATH", "no"))
        issues.append("add ~/.local/bin to your shell's PATH")

    print("\n" + rule("user systemd", w))
    rc, out = sh("systemctl --user is-system-running 2>&1")
    state = out.strip().splitlines()[-1] if out.strip() else ""
    # "degraded" still runs units; anything else (e.g. "Failed to connect to
    # bus") means no user manager at all.
    has_user = state in ("running", "degraded", "starting", "initializing")
    print(row(OK if has_user else BAD, "systemd --user session", state if has_user else "NO",
              note="" if has_user else "minimal installs may lack libpam-systemd / dbus-user-session"))
    if not has_user: blockers.append("no user systemd: no watchdog and no mounts")
    _, ling = sh("loginctl show-user $(id -un) -p Linger --value")
    ok_l = ling.strip() == "yes"
    print(row(OK if ok_l else WARN, "linger", ling or "?",
              note="" if ok_l else "without it the deck dies when you log out"))
    if not ok_l: issues.append("sudo loginctl enable-linger $(id -un)")

    print("\n" + rule("FUSE (fleet mounts)", w))
    devf = os.path.exists("/dev/fuse")
    fm = have("fusermount3") or have("fusermount")
    print(row(OK if devf else BAD, "/dev/fuse", "present" if devf else "missing"))
    print(row(OK if fm else BAD, "fusermount", fm or "missing"))
    if devf and fm:
        print(row(OK, "strategy", "rclone (static binary, no sudo)"))
    else:
        blockers.append("no FUSE, no fleet file tree")

    # mosh-server refuses to start without the client's UTF-8 locale, and
    # Termux sends en_US.UTF-8.
    print("\n" + rule("locales", w))
    _, locs = sh("locale -a 2>/dev/null")
    ll = locs.lower()
    for want, why in (("c.utf8", "the bare minimum"), ("en_us.utf8", "what Termux sends")):
        ok = want.replace("-", "") in ll.replace("-", "")
        print(row(OK if ok else WARN, want, "yes" if ok else "MISSING", note=why))
        if not ok and want == "en_us.utf8":
            issues.append("mosh from Termux will fail unless you force LC_ALL=C.UTF-8")

    print("\n" + rule("privileges and packages", w))
    rc, _ = sh("sudo -n true 2>&1")
    lvl = "passwordless" if rc == 0 else ("with password" if have("sudo") else "no sudo")
    print(row(OK if have("sudo") else WARN, "sudo", lvl))
    mgrs = [m for m in ("apt-get","dnf","rpm-ostree","pacman","apk","zypper","brew",
                                 "flatpak","cargo","go","npm","uv","pipx") if have(m)]
    print(row(OK if mgrs else WARN, "package managers", ", ".join(mgrs) or "none",
              note="" if any(m in mgrs for m in ("cargo","go")) else "no toolchain: release binaries only"))

    print("\n" + rule("deck binaries", w))
    remotes = [h for h in (profile or {}).get("hosts", []) if not h.get("local")]
    need = {"zellij": "essential", "ssh": "fleet" if remotes else "optional", "rclone": "mounts",
            "mosh-server": "mosh clients (optional)", "yazi": "files", "btop": "system",
            "gping": "network", "ctop": "containers"}
    for b, why in need.items():
        p = have(b)
        crit = (b == "zellij") or (b == "ssh" and remotes)
        print(row(OK if p else (BAD if crit else WARN), b, p or "missing", note=why))
        if not p and crit:
            blockers.append("%s is missing" % b + (" and the profile declares remote hosts" if b == "ssh" else ""))

    print("\n" + rule("fleet", w))
    if not profile:
        print(row(OK, "profile", "none yet", note="phosphor init comes next"))
    # Someone else's profile (the example) declares another machine as local:
    # without this warning the checks below make no sense to whoever runs them.
    if profile:
        me = os.uname().nodename
        loc = [h["name"] for h in profile.get("hosts", []) if h.get("local")]
        if loc and me not in loc:
            print(row(AMB, "not your profile",
                      "it declares '%s' as local, but you're on '%s'" % (loc[0], me)))
            print("      " + DIM + "the checks below don't apply. Run: phosphor init" + RST)
            issues.append("the profile isn't this machine's: run phosphor init")
    import mesh
    kind, control = mesh.current(profile)
    if kind == "none":
        print(row(OK, "network", "plain ssh", note='mesh = "none" in the profile'))
    elif have("tailscale"):
        rc, out = sh("tailscale status 2>/dev/null | grep -vc offline")
        print(row(OK, kind, "%s peers online" % (out or "?"), note=control or ""))
    else:
        print(row(WARN, kind, "the tailscale client is missing",
                  note='headscale uses it too; or set mesh = "none"'))
    if profile:
        for h in profile.get("hosts", []):
            if h.get("local"):
                print(row(OK, h["name"], "local (brain)")); continue
            alias = h.get("ssh") or h["name"]
            rc, out = sh("ssh -o BatchMode=yes -o ConnectTimeout=6 %s 'echo ok' 2>&1" % alias, t=12)
            good = out.strip().endswith("ok")
            print(row(OK if good else BAD, h["name"], "ssh ok" if good else out[:38],
                      note=h.get("role", "")))
            if not good: issues.append("%s doesn't answer over ssh" % h["name"])
            if h.get("mount"):
                import deckconf, fleet
                mp = os.path.join(deckconf.mount_root(profile), h["name"])
                mounted = os.path.ismount(mp)
                # A dead SFTP transport (the remote slept, or changed IP over
                # Tailscale) leaves the kernel still listing mp as mounted --
                # os.path.ismount() alone can't tell it apart from a healthy
                # one. `phosphor fleet`'s own background sweep self-heals
                # this now (fusermount -uz + restart the unit); this just
                # says so instead of reporting "mounted" on a dead mount.
                zombie = mounted and deckconf.mount_zombie(mp)
                state = "zombie: transport dead, self-heals within %ds" % fleet.MOUNT_CHECK_S \
                        if zombie else ("mounted" if mounted else "not mounted: it will look empty")
                print(row(WARN if zombie else (OK if mounted else BAD),
                          "  " + mp.replace(os.path.expanduser("~"), "~", 1), state,
                          note="" if mounted and not zombie else "journalctl --user -u fleet-%s" % h["name"]))
                if zombie:
                    issues.append("~/fleet/%s's transport died: phosphor fleet self-heals it "
                                  "within %ds (fusermount -uz + restart fleet-%s.service by hand "
                                  "if it doesn't)" % (h["name"], fleet.MOUNT_CHECK_S, h["name"]))
                if not mounted:
                    issues.append("~/fleet/%s isn't mounted: journalctl --user -u fleet-%s" % (h["name"], h["name"]))
                    # The mount runs as a systemd service, not in this terminal: a key
                    # behind a passphrase works here (the desktop's agent) and not there.
                    if good and have("systemd-run"):
                        tgt = alias if "@" in alias or not h.get("user") else "%s@%s" % (h["user"], alias)
                        rc2, out2 = sh("systemd-run --user --pipe --wait --quiet ssh -o BatchMode=yes "
                                       "-o ConnectTimeout=6 %s 'echo ok' 2>&1" % tgt, t=20)
                        if not out2.strip().endswith("ok"):
                            print(row(BAD, "  from a service", "ssh fails there: " + (out2.strip().splitlines() or ["?"])[-1][:36],
                                      note="the mounts run as one"))
                            issues.append("ssh to %s works here but not from a service: a key with a passphrase "
                                          "needs the agent there (systemctl --user import-environment SSH_AUTH_SOCK)" % h["name"])

    folder = (profile or {}).get("notes", {}).get("folder") if profile else None
    if folder:
        print("\n" + rule("notebook", w))
        f = os.path.expanduser(folder)
        exists = os.path.isdir(f)
        writable = exists and os.access(f, os.W_OK)
        print(row(OK if writable else BAD, "notes folder", f.replace(HOME, "~", 1),
                  note="" if writable else ("missing" if not exists else "not writable")))
        if not writable:
            issues.append("the notes folder isn't there or isn't writable: %s" % f.replace(HOME, "~", 1))

    if profile and profile.get("tunnels"):
        import tunnels
        fw = tunnels.ssh_config_forwards()
        for t in profile["tunnels"]:
            h = t.get("host", "?")
            up = tunnels.active(h)
            ports = [p for p, _, _ in fw.get(h, [])]
            live = sum(1 for p in ports if tunnels.listening(p))
            print(row(OK if up and live == len(ports) else WARN, "tunnel " + h,
                      "%s · %d/%d listening" % ("up" if up else "down", live, len(ports))))
            if not up: issues.append("tunnel %s is down: journalctl --user -u %s" % (h, tunnels.unit_name(h)))

    print("\n" + rule("summary", w))
    if blockers:
        for b in blockers: print("  " + BAD + " " + RED + b + RST)
    if issues:
        for i in issues: print("  " + WARN + " " + AMB + i + RST)
    if not blockers and not issues:
        print("  " + OK + " " + PH + "all good — you can run phosphor gen" + RST)
    elif not blockers:
        print("  " + DIM + "nothing blocking: the deck starts, with those warnings" + RST)
    print()
    return 2 if blockers else (1 if issues else 0)
