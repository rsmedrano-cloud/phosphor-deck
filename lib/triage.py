"""phosphor triage HOST [--assistant NAME] - a diagnostic snapshot of a
fleet host, straight to whichever AI assistant is installed.

    phosphor triage HOST
    phosphor triage                 lists what the fleet panel is flagging

A deeper, one-off look than the regular fleet poll (load, failed systemd
units, memory, disk, recent kernel messages) over ssh, piped straight into
`phosphor ask` with a fixed question: what's actually wrong here, and how
do I fix it. Not something to run on a timer -- for when `phosphor fleet`
or `phosphor doctor` already told you something's off and you want a
second look before you go digging by hand. With no HOST, it doesn't guess:
it shows whatever the fleet panel currently thinks needs attention (same
list `phosphor glance` shows) so you can pick one.
"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BAD, DIM, RST
import deckconf
from tail import find_host

SNAPSHOT_SH = """
echo "== uptime & load =="
uptime 2>/dev/null
echo
echo "== failed systemd units =="
systemctl --failed --no-legend 2>/dev/null || echo "(systemctl not available)"
echo
echo "== memory =="
free -h 2>/dev/null
echo
echo "== disk =="
df -h 2>/dev/null | grep -Ev '^(tmpfs|devtmpfs|overlay|Filesystem)'
echo
echo "== recent kernel messages =="
dmesg --ctime 2>/dev/null | tail -n 30 || journalctl -k -n 30 --no-pager 2>/dev/null || echo "(no kernel log access)"
"""

QUESTION = ("Diagnose this host from the snapshot above: what's actually wrong (if anything), "
            "and what commands would you run to fix it?")


def snapshot(h, timeout=20):
    """(text, None) or (None, why) -- the same sh -s over ssh delivery
    share/collect.sh already uses, so there's no quoting to get wrong on a
    multi-line script."""
    cmd = ["sh", "-s"] if h.get("local") else \
          ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", deckconf.target(h), "sh -s"]
    try:
        r = subprocess.run(cmd, input=SNAPSHOT_SH, capture_output=True, text=True, timeout=timeout)
    except subprocess.SubprocessError as e:
        return None, str(e)
    if not r.stdout.strip():
        return None, (r.stderr or "no answer").strip()[:200] or "no output"
    return r.stdout, None


def list_flagged():
    import glance
    ok, total, bad = glance.fleet_state()
    if not bad:
        print(DIM + "  nothing the fleet panel is flagging right now." + RST)
        return 0
    print(DIM + "  usage: phosphor triage HOST -- currently flagged:" + RST)
    for name, detail in bad:
        print("    " + name + ": " + detail)
    return 1


def main():
    a = sys.argv[1:]
    if a and a[0] in ("-h", "--help"):
        print("usage: phosphor triage [--assistant NAME] HOST"); return 0
    assistant = None
    if a[:1] == ["--assistant"]:
        if len(a) < 2:
            print(BAD + " --assistant needs a name" + RST); return 1
        assistant, a = a[1], a[2:]
    if not a:
        return list_flagged()
    host = a[0]
    prof, _ = deckconf.load()
    h = find_host(prof, host)
    if not h:
        known = ", ".join(x["name"] for x in deckconf.hosts(prof)) or "(none in your profile)"
        print(BAD + " no host named %r in your profile -- have: %s" % (host, known) + RST)
        return 1
    print(DIM + "  collecting a snapshot from " + host + "..." + RST)
    text, err = snapshot(h)
    if text is None:
        print(BAD + " couldn't reach %s: %s" % (host, err) + RST); return 1
    import ask
    chosen = ask.pick(assistant)
    if chosen is None:
        if assistant:
            print(BAD + " %r isn't installed, or isn't one phosphor ask knows (%s)" %
                  (assistant, ", ".join(ask.ONESHOT)) + RST)
        else:
            print(BAD + " no assistant installed: " + ", ".join(ask.ONESHOT) + RST)
        return 1
    print(DIM + "  asking " + chosen + "..." + RST)
    full = ask.prompt([QUESTION], text)
    try:
        return subprocess.run(ask.command(chosen, full)).returncode
    except OSError as e:
        print(BAD + " couldn't run %s: %s" % (chosen, e) + RST); return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
