#!/usr/bin/env python3
"""Text from outside the brain is data, never terminal commands.

A fleet host's poll answer, a container's logs, a chat message, a pull
request's title: any of it can carry escape sequences, and printed as-is
they reach the terminal of every screen on the deck. An OSC 52 there writes
the clipboard of every device looking at it (zellij passes it on), others
retitle panes, move the cursor to repaint what's above, or hide a line. A
compromised host, or anyone who can get a line into a container's log,
shouldn't be able to do any of that.

  clean(s)         one field (a name, a status, a title): every escape
                   sequence and control character goes, newlines and tabs
                   become spaces.
  clean_text(s)    many lines (logs, a command's output): same, but lines
                   stay lines and plain colors (SGR) stay colors.
  clean_tree(x)    clean() on every string inside parsed JSON (lines=True
                   keeps newlines, for a caller that cuts them itself).

Also a filter for streams that never end (`phosphor tail`):

  python3 sanitize.py -- CMD...    runs CMD with its output through
                                   clean_text, line by line, and exits
                                   with CMD's own status (so a dropped ssh
                                   still says 255 and gets reconnected).
"""
import os, re, signal, subprocess, sys

_SEQ = (r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"                         # CSI (colors, cursor, ...)
        r"|(?:\x1b[\]PX^_]|[\x90\x98\x9d\x9e\x9f]).*?(?:\x07|\x1b\\|\x9c|$)"  # OSC, DCS... to their end
        r"|\x1b[ -/]*[0-~]"                                          # the other escapes (ESC c resets)
        r"|\x1b")                                                    # a lone ESC
# Bidi overrides and isolates: they make a line read differently from
# what it says (a "trojan source" filename).
_BIDI = r"\u202a-\u202e\u2066-\u2069"
_ONE  = re.compile(_SEQ + r"|[\x00-\x1f\x7f-\x9f" + _BIDI + "]", re.S)
_TEXT = re.compile(_SEQ + r"|\r(?!\n)|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f" + _BIDI + "]", re.S)
_SGR  = re.compile(r"\x1b\[[0-9;:]*m\Z")


def clean(s, lines=False):
    """`lines`: newlines stay (a commit message cut to its first line later)."""
    if not isinstance(s, str):
        return s
    keep = "\n" if lines else ""
    return _ONE.sub(lambda m: m.group(0) if m.group(0) == keep else
                    " " if m.group(0) in "\t\n" else "", s)


def clean_text(s):
    if not isinstance(s, str):
        return s
    return _TEXT.sub(lambda m: m.group(0) if _SGR.match(m.group(0)) else "", s)


def clean_tree(x, lines=False):
    if isinstance(x, str):
        return clean(x, lines)
    if isinstance(x, list):
        return [clean_tree(v, lines) for v in x]
    if isinstance(x, tuple):
        return tuple(clean_tree(v, lines) for v in x)
    if isinstance(x, dict):
        return {clean(k): clean_tree(v, lines) for k, v in x.items()}
    return x


def pipe(argv, out=None):
    """Run argv, its stdout and stderr through clean_text line by line;
    its exit status back. Ctrl-C belongs to the command (ssh -t sends it to
    the host), so this side ignores it and just waits for the end."""
    out = out or sys.stdout.buffer
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL))
    except OSError as e:
        out.write(("%s: %s\n" % (argv[0], e.strerror)).encode()); out.flush()
        return 127
    for line in iter(p.stdout.readline, b""):
        try:
            out.write(clean_text(line.decode("utf-8", "replace")).encode("utf-8"))
            out.flush()
        except BrokenPipeError:
            break
    return p.wait()


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--"]:
        a = a[1:]
    if not a:
        print("usage: sanitize.py -- CMD [ARGS...]"); sys.exit(1)
    sys.exit(pipe(a))
