"""phosphor ask - a one-shot question, no tab.

    phosphor ask [--assistant NAME] [-c] QUESTION
    cmd | phosphor ask [QUESTION]

Shells out to whichever assistant CLI is already installed and prints its
answer inline: no tab, no context switch, for the "what was that command
again" class of question. Same assistants `phosphor workspace` already
knows (claude, gemini, codex, opencode, aider, agy), tried in that order
unless --assistant names one. Nothing new to install: if none of them are
on this machine, it says so instead of reaching for a dependency of its own.

Piped input is context, not a replacement for the question: `git diff |
phosphor ask "what changed here"` sends the diff and the question together.
With no question at all, the piped text alone is the prompt.

-c (--notes) puts your notebook's latest decisions and summaries in front,
so the answer knows what you've already settled: "why did we drop X" has
something to go on. Off unless asked: those notes go to the assistant's
provider along with the question.

Run with nothing at all on a terminal it asks instead: a box for the
question, whether the notebook goes along, and the answer in a pager.

--here is the deck's ask key (Alt-q): it opens in place of the pane you're
in and sends what that pane shows (its last lines, its tab, its title)
along with the question, so "what does this error mean" needs no copying.
The box says how many lines go to which assistant before anything leaves.
That text wasn't written by the deck, so the assistant runs with no tools
(as triage does). Esc, or q on the answer, gives the pane back.
"""
import os, shutil, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BAD, DIM, RST
import newtab

# argv prefix that runs the assistant non-interactively: send one question,
# print the answer to stdout, exit. Distinct from workspace.py's FIRST,
# which starts an assistant and leaves it running interactively with a
# first message -- ask never leaves anything open.
ONESHOT = {
    "claude": ["claude", "-p"],
    "gemini": ["gemini", "-p"],
    "codex": ["codex", "exec"],
    "opencode": ["opencode", "run"],
    "aider": ["aider", "--yes-always", "--message"],
    "agy": ["agy", "-p"],
}
ORDER = ["claude", "gemini", "codex", "opencode", "aider", "agy"]

# The same, for a question built from text the deck didn't write (triage's
# snapshot of a host): no tools at all, or each CLI's read-only mode, so a
# log line that talks the assistant into "running a quick fix" has nothing
# to run it with. Headless, a tool that needs approval is denied anyway;
# this holds even where your own settings would allow it.
READONLY = {
    "claude": ["claude", "--tools", "", "-p"],
    "gemini": ["gemini", "--approval-mode", "plan", "-p"],
    "codex": ["codex", "exec", "--sandbox", "read-only"],
    "opencode": ["opencode", "run", "--agent", "plan"],
    "aider": ["aider", "--dry-run", "--no-auto-commits", "--no-suggest-shell-commands",
              "--yes-always", "--message"],
    "agy": ["agy", "--mode", "plan", "--sandbox", "-p"],
}


def pick(name=None):
    """The assistant to run: `name` if it's one ask knows and is installed,
    else the first installed one in ORDER. None if there's no match."""
    if name:
        return name if name in ONESHOT and newtab.have(name) else None
    return next((a for a in ORDER if newtab.have(a)), None)


def command(assistant, question, readonly=False):
    """The argv, its program by full path: a pane of the deck runs with
    the PATH systemd gave zellij, which may not have ~/.local/bin, where
    pick() found it."""
    argv = (READONLY if readonly else ONESHOT)[assistant] + [question]
    found = shutil.which(argv[0]) or newtab.have(argv[0])     # PATH first, as a shell would
    return [found if isinstance(found, str) else argv[0]] + argv[1:]


NOTE_KINDS = ("decision", "summary")
NOTE_COUNT = 5
NOTE_CHARS = 1500      # per note: one long summary shouldn't crowd out the rest


def recent_notes(entries, n=NOTE_COUNT):
    """The notebook's latest decisions and summaries (entries newest first,
    as notes.entries() gives them) as one block of text, or "" if none."""
    picked = [e for e in entries if e["kind"] in NOTE_KINDS][:n]
    if not picked:
        return ""
    parts = []
    for e in picked:
        raw = e["raw"]
        parts.append(raw if len(raw) <= NOTE_CHARS else raw[:NOTE_CHARS].rstrip() + " [...]")
    return ("For context, the latest decisions and summaries from my notebook "
            "(newest first):\n\n" + "\n\n".join(parts))


def prompt(argv, piped, notes=""):
    """The words on the command line, piped input if there was any, and both
    together when there's both -- piped text first, as context, then the
    question, the way you'd hand someone a diff before asking about it.
    Notes (-c) go before everything: the oldest, widest context first."""
    question = " ".join(argv).strip()
    body = piped + "\n\n" + question if piped and question else question or piped
    return notes + "\n\n" + body if notes and body else body


def no_assistant(assistant):
    if assistant:
        print(BAD + " %r isn't installed, or isn't one phosphor ask knows (%s)" %
              (assistant, ", ".join(ONESHOT)) + RST)
    else:
        print(BAD + " no assistant installed: " + ", ".join(ONESHOT) + RST)
    return 1


CONTEXT_LINES = 120
CONTEXT_CHARS = 12000


def last_lines(text, n=CONTEXT_LINES, chars=CONTEXT_CHARS):
    """A pane's dump, its trailing blank rows off, its last n lines and at
    most `chars` of them: the end of a screen is where the error is."""
    rows = [r.rstrip() for r in (text or "").splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    rows = rows[-n:]
    while rows and sum(len(r) + 1 for r in rows) > chars:
        rows.pop(0)
    while rows and not rows[0]:
        rows.pop(0)
    return "\n".join(rows)


def screen_context(tab, title, text):
    """The pane, as the assistant gets it: where it is, then what it shows."""
    where = "tab %s" % tab + (", pane %s" % title if title else "")
    return ("This is what a terminal pane of mine shows right now (%s), its last "
            "%d lines:\n\n```\n%s\n```" % (where, len(text.splitlines()), text))


def covered_pane():
    """(tab, pane title, its last lines) of the pane the ask key opened over,
    or None: outside the deck, or nothing under this pane."""
    if not os.environ.get("ZELLIJ_PANE_ID"):
        return None
    import edit
    here = edit.where_am_i()
    if not here or here[3] is None:
        return None
    _, _, tab, covered = here
    title = next((p.get("title", "") for p in edit.panes() if p["id"] == covered and not p["is_plugin"]), "")
    text = last_lines(key_dump() or newtab.zj("dump-screen", "--full", "--pane-id", "terminal_%d" % covered))
    return tab, title, text


def key_dump(fresh=30):
    """What the key had zellij dump just before covering the pane, read
    once (it may hold anything the screen did) and only if it's from this
    press, not one that never got read."""
    import shortcuts
    path = shortcuts.screen_dump()
    try:
        recent = time.time() - os.path.getmtime(path) < fresh
        text = open(path, encoding="utf-8", errors="replace").read() if recent else ""
        os.remove(path)
    except OSError:
        return ""
    return text


def interactive_here(assistant):
    """The ask key: a question about the pane it covers, its screen along."""
    import form
    chosen = pick(assistant)
    if chosen is None:
        return no_assistant(assistant)
    pane = covered_pane()
    if not pane or not pane[2]:
        return interactive(assistant, False)
    tab, title, text = pane
    n = len(text.splitlines())
    q = form.line("phosphor ask · " + tab,
                  "about this pane: its last %d lines go to %s's provider -- Enter asks, Esc goes back" % (n, chosen))
    if not (q or "").strip():
        form.leave(); return 0
    form.leave()
    print(DIM + "  asking " + chosen + " about " + tab + "..." + RST)
    try:
        r = subprocess.run(command(chosen, prompt([q], screen_context(tab, title, text)), readonly=True),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        print(BAD + " couldn't run %s: %s" % (chosen, e) + RST); return 1
    form.pager("  " + q + "\n\n" + r.stdout.decode("utf-8", "replace"))
    return r.returncode


def interactive(assistant, with_notes):
    """No question and a terminal: a box for it, the notebook or not, the
    answer in a pager."""
    import form, edit
    chosen = pick(assistant)
    if chosen is None:
        return no_assistant(assistant)
    q = form.line("phosphor ask", "a question for %s -- Enter asks, Esc goes back" % chosen)
    if not (q or "").strip():
        form.leave(); return 0
    if not with_notes:
        how = edit.pick("send your notebook along?",
                        [("just ask", "only the question"),
                         ("with notes", "its 5 latest decisions and summaries go too, to %s's provider" % chosen)])
        if how is None:
            form.leave(); return 0
        with_notes = how[0] == "with notes"
    notes_text = ""
    if with_notes:
        import notes
        notes_text = recent_notes(notes.entries())
    form.leave()
    print(DIM + "  asking " + chosen + "..." + RST)
    try:
        r = subprocess.run(command(chosen, prompt([q], "", notes_text)),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError as e:
        print(BAD + " couldn't run %s: %s" % (chosen, e) + RST); return 1
    form.pager("  " + q + "\n\n" + r.stdout.decode("utf-8", "replace"))
    return r.returncode


def main():
    a = sys.argv[1:]
    assistant, with_notes, here = None, False, False
    while a and a[0] in ("--assistant", "-c", "--notes", "--here"):
        if a[0] == "--assistant":
            if len(a) < 2:
                print(BAD + " --assistant needs a name" + RST); return 1
            assistant, a = a[1], a[2:]
        elif a[0] == "--here":
            here, a = True, a[1:]
        else:
            with_notes, a = True, a[1:]
    if here:
        return interactive_here(assistant)
    piped = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    if not (a or piped):
        if sys.stdin.isatty() and sys.stdout.isatty():
            return interactive(assistant, with_notes)
        print(BAD + " usage: phosphor ask [--assistant NAME] [-c] \"question\"   (or pipe one in)" + RST); return 1
    notes_text = ""
    if with_notes:
        import notes
        notes_text = recent_notes(notes.entries())
        if not notes_text:
            print(DIM + " -c: no decisions or summaries in the notebook yet, asking without them" + RST,
                  file=sys.stderr)
    question = prompt(a, piped, notes_text)
    chosen = pick(assistant)
    if chosen is None:
        return no_assistant(assistant)
    try:
        return subprocess.run(command(chosen, question)).returncode
    except OSError as e:
        print(BAD + " couldn't run %s: %s" % (chosen, e) + RST); return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
