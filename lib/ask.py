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
"""
import os, subprocess, sys
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


def pick(name=None):
    """The assistant to run: `name` if it's one ask knows and is installed,
    else the first installed one in ORDER. None if there's no match."""
    if name:
        return name if name in ONESHOT and newtab.have(name) else None
    return next((a for a in ORDER if newtab.have(a)), None)


def command(assistant, question):
    return ONESHOT[assistant] + [question]


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


def main():
    a = sys.argv[1:]
    assistant, with_notes = None, False
    while a and a[0] in ("--assistant", "-c", "--notes"):
        if a[0] == "--assistant":
            if len(a) < 2:
                print(BAD + " --assistant needs a name" + RST); return 1
            assistant, a = a[1], a[2:]
        else:
            with_notes, a = True, a[1:]
    piped = sys.stdin.read().strip() if not sys.stdin.isatty() else ""
    if not (a or piped):
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
        if assistant:
            print(BAD + " %r isn't installed, or isn't one phosphor ask knows (%s)" %
                  (assistant, ", ".join(ONESHOT)) + RST)
        else:
            print(BAD + " no assistant installed: " + ", ".join(ONESHOT) + RST)
        return 1
    try:
        return subprocess.run(command(chosen, question)).returncode
    except OSError as e:
        print(BAD + " couldn't run %s: %s" % (chosen, e) + RST); return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
