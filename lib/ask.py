"""phosphor ask - a one-shot question, no tab.

    phosphor ask [--assistant NAME] QUESTION

Shells out to whichever assistant CLI is already installed and prints its
answer inline: no tab, no context switch, for the "what was that command
again" class of question. Same assistants `phosphor workspace` already
knows (claude, gemini, codex, opencode, aider), tried in that order unless
--assistant names one. Nothing new to install: if none of them are on this
machine, it says so instead of reaching for a dependency of its own.
"""
import os, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import BAD, RST
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
}
ORDER = ["claude", "gemini", "codex", "opencode", "aider"]


def pick(name=None):
    """The assistant to run: `name` if it's one ask knows and is installed,
    else the first installed one in ORDER. None if there's no match."""
    if name:
        return name if name in ONESHOT and newtab.have(name) else None
    return next((a for a in ORDER if newtab.have(a)), None)


def command(assistant, question):
    return ONESHOT[assistant] + [question]


def main():
    a = sys.argv[1:]
    assistant = None
    if a[:1] == ["--assistant"]:
        if len(a) < 2:
            print(BAD + " --assistant needs a name" + RST); return 1
        assistant, a = a[1], a[2:]
    question = " ".join(a).strip()
    if not question:
        print(BAD + " usage: phosphor ask [--assistant NAME] \"question\"" + RST); return 1
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
