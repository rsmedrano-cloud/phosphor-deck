#!/usr/bin/env python3
"""Play the first-time user in a clean Debian: `sh install.sh` on a real
terminal (a pty), Enter on every question, and expect to end INSIDE the
deck. Then a `phosphor restart` from outside must bring the screen back in
by itself; then Ctrl-q (detach) and check the deck is still running.

    python3 tests/tester-sim.py          (needs docker; ~5 minutes)

Uses the image from Containerfile.test and the committed tree (git archive).
"""
import os, pty, re, select, subprocess, sys, time

C = "phosphor-tester-sim"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# OSC ends with BEL or ST (ESC \); matching only BEL once swallowed whole screens
ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[()][A-Z0-9]|\r")
# the start of one of those, cut off at the end of a read
PARTIAL = re.compile(rb"\x1b(?:\[[0-9;?]*|\][^\x07\x1b]*\x1b?|[()])?\Z")

def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)

def setup():
    sh("docker", "rm", "-f", C)
    if sh("docker", "build", "-q", "-t", "phosphor-test", "-f", "Containerfile.test", ".", cwd=HERE).returncode:
        sys.exit("image build failed")
    sh("docker", "run", "-d", "--name", C, "--privileged", "--tmpfs", "/run", "--tmpfs", "/run/lock", "phosphor-test")
    for _ in range(30):
        if "running" in sh("docker", "exec", C, "systemctl", "is-system-running").stdout or \
           "degraded" in sh("docker", "exec", C, "systemctl", "is-system-running").stdout: break
        time.sleep(1)
    tar = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=HERE, capture_output=True).stdout
    subprocess.run(["docker", "exec", "-i", C, "sh", "-c",
                    "mkdir -p /home/deck/phosphor-src && tar -x -C /home/deck/phosphor-src && chown -R deck:deck /home/deck/phosphor-src"],
                   input=tar)
    sh("docker", "exec", C, "loginctl", "enable-linger", "deck")
    for _ in range(20):
        if sh("docker", "exec", C, "test", "-S", "/run/user/1000/bus").returncode == 0: break
        time.sleep(1)

class Screen:
    """The pty's bytes as they come (raw), and as text: ANSI stripped from
    each new chunk only, an escape split across two reads held back until
    it's whole. Re-stripping the whole log on every pass once fell behind
    zellij's first frames under load, and zellij dropped the client (#106)."""
    def __init__(self):
        self.raw, self.text, self.carry = bytearray(), bytearray(), b""
    def feed(self, data):
        self.raw += data
        chunk, self.carry = self.carry + data, b""
        m = PARTIAL.search(chunk, max(0, len(chunk) - 4096))
        if m:
            chunk, self.carry = chunk[:m.start()], chunk[m.start():]
        self.text += ANSI.sub(b"", chunk)

def run():
    argv = ["docker", "exec", "-it", "-u", "deck", "-e", "HOME=/home/deck", "-e", "USER=deck",
            "-e", "XDG_RUNTIME_DIR=/run/user/1000", "-e", "TERM=xterm-256color", "-e", "SHELL=/bin/bash",
            "-w", "/home/deck", C, "sh", "/home/deck/phosphor-src/install.sh"]
    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(argv[0], argv)
    import fcntl, termios, struct
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
    os.set_blocking(fd, False)
    s, answered, inside_at, end = Screen(), 0, None, time.time() + 540
    restart = back_at = answer_at = gone_at = None
    asked = 0                          # the text before this was answered already
    eof = False
    while time.time() < end and not eof:
        # never sleep while zellij draws: wait for bytes, or for the answer that's due
        wait = 0.2 if answer_at is None else max(0.0, min(0.2, answer_at - time.time()))
        r, _, _ = select.select([fd], [], [], wait)
        if r:
            while True:                # drain all there is, then look
                try: data = os.read(fd, 65536)
                except BlockingIOError: break
                except OSError: eof = True; break
                if not data: eof = True; break
                s.feed(data)
        now = time.time()
        if answer_at is not None:
            if now >= answer_at:
                os.write(fd, b"\r"); answered += 1; answer_at = None; asked = len(s.text)
            continue
        tail = bytes(s.text[max(asked, len(s.text) - 600):])
        # every question: take the default, a beat later as a person would
        if re.search(rb"(\[Y/n\]|\(Y/n\)|\(y/N\)|Enter to choose|Enter to go in|\? number \[\d+\])\s*$", tail.rstrip(b" ")) or \
           tail.rstrip().endswith((b"[Y/n]", b"(Y/n)", b"(y/N)", b"Enter to go in")):
            answer_at = now + 0.3
            continue
        # inside the deck: the tab bar shows the deck's tabs
        if inside_at is None:
            w = s.text[-4000:]
            if b"NOTES" in w and b"DECK" in w and b"Zellij" in w:
                inside_at = now
        # a restart from elsewhere kicks us out: deck must bring us back in
        if inside_at and restart is None and now - inside_at > 4:
            restart = subprocess.Popen(["docker", "exec", "-u", "deck", "-e", "HOME=/home/deck",
                                        "-e", "XDG_RUNTIME_DIR=/run/user/1000", C,
                                        "/home/deck/.local/bin/phosphor", "restart"],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            looked = len(s.text)
        if restart is not None and back_at is None:
            # look at the new text only, a word's length back for one split across reads
            if gone_at is None:
                i = s.text.find(b"the deck is restarting", max(0, looked - 40))
                if i >= 0: gone_at, notes, deck = i, False, False
            if gone_at is not None:
                notes = notes or s.text.find(b"NOTES", max(gone_at, looked - 8)) >= 0
                deck = deck or s.text.find(b"DECK", max(gone_at, looked - 8)) >= 0
                if notes and deck: back_at = now
            looked = len(s.text)
        if back_at and now - back_at > 4:
            os.write(fd, b"\x11")              # Ctrl-q: detach
            time.sleep(3)
            break
    if restart is not None:
        try: restart.wait(timeout=90)
        except subprocess.TimeoutExpired: restart.kill()
    try: os.kill(pid, 9); os.waitpid(pid, 0)
    except OSError: pass
    return bytes(s.raw), answered, inside_at is not None, back_at is not None

def main():
    os.chdir(HERE)
    print("== clean container"); setup()
    print("== sh install.sh on a terminal, Enter to everything")
    log, answered, inside, back = run()
    text = ANSI.sub(b"", log).decode("utf-8", "ignore")
    keep = [l for l in text.splitlines() if re.search(r"set it up now|\?|✓ (profile|deck|session)|skipped|next:|get in|FAIL|Error|Traceback", l)]
    print("\n".join("   " + l.strip()[:110] for l in keep[-30:]))
    print("== questions answered with Enter: %d" % answered)
    alive = sh("docker", "exec", "-u", "deck", "-e", "XDG_RUNTIME_DIR=/run/user/1000", C,
               "/home/deck/.local/bin/zellij", "list-sessions", "-n").stdout
    print("== ended inside the deck:", inside)
    print("== back inside by itself after a restart:", back)
    print("== deck still running after Ctrl-q:", "deck " in alive)
    ok = inside and back and "deck " in alive
    if not ok:
        print("== the last screen, as text:")
        print("\n".join("   " + l[:110] for l in text.splitlines()[-40:]))
    print("\n%s" % ("PASS: one command, from nothing to inside the deck" if ok else "FAIL"))
    if not os.environ.get("KEEP"): sh("docker", "rm", "-f", C)
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
