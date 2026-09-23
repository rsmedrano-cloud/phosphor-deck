"""phosphor clip - a file or a pipe onto the clipboard of the device you're
looking at the deck from, or what you paste into a file.

    phosphor clip notes.txt          file -> clipboard
    git log -1 | phosphor clip       pipe -> clipboard
    phosphor clip --save out.txt     paste, then Ctrl-D -> file

It writes OSC 52 to the terminal. zellij forwards it to every attached
device, so a phone and a PC on the deck at the same time both get it.
"""
import base64, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

# Termux accepts ~100 KB of OSC 52 (Android's clipboard transaction limit)
# and silently drops more. Base64 grows the text by a third.
MAX = 70 * 1024

def say(s):
    print(s, file=sys.stderr)

def send(data):
    if len(data) > MAX:
        say(row(BAD, "too big", "%d KB, the clipboard takes ~%d KB" % (len(data) // 1024, MAX // 1024),
                note="move files through ~/fleet"))
        return 1
    seq = "\x1b]52;c;" + base64.b64encode(data).decode() + "\x07"
    try:
        with open("/dev/tty", "w") as t:
            t.write(seq); t.flush()
    except OSError:
        say(row(BAD, "no terminal", "run it from a pane of the deck or an ssh session"))
        return 1
    say(row(OK, "clipboard", "%d bytes" % len(data), note="paste it on your device"))
    return 0

def save(path, force):
    if os.path.exists(path) and not force:
        say(row(BAD, path, "already exists", note="--force to overwrite")); return 1
    say(DIM + "  paste now, then Ctrl-D on an empty line" + RST)
    data = sys.stdin.read()
    with open(path, "w") as f:
        f.write(data)
    say(row(OK, "saved", path, note="%d bytes" % len(data.encode())))
    return 0

def main():
    a = sys.argv[1:]
    if "--save" in a:
        i = a.index("--save")
        if i + 1 >= len(a):
            say("usage: phosphor clip --save FILE [--force]"); return 1
        return save(a[i + 1], "--force" in a)
    if a and a[0] != "-":
        try:
            data = open(a[0], "rb").read()
        except OSError as e:
            say(row(BAD, a[0], str(e))); return 1
    elif not sys.stdin.isatty():
        data = sys.stdin.buffer.read()
    else:
        say("usage: phosphor clip FILE | cmd | phosphor clip | phosphor clip --save FILE")
        return 1
    return send(data)

if __name__ == "__main__":
    sys.exit(main() or 0)
