"""The events file: one line per thing that happened, for the SYS adjutant
(the latest one) and the while-you-were-away screen (what came since you
left, lib/away.py).

    TAB<TAB>TEXT<TAB>SECONDS

Anyone appends (phosphor notify, the chat hook), so a reader takes it as
text, never escapes. A line from before 2.4.7 has no time and counts as
long ago. The time goes last so an adjutant still running older code shows
it at the end of the text, instead of taking it for the tab.
"""
import os, time
import deckconf


def path():
    return os.path.join(deckconf.cache_dir(), "events")


def append(tab, text, now=None):
    """One line, its tabs and newlines flattened: one event, one line."""
    p = path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    flat = lambda s: " ".join(str(s).split())
    with open(p, "a") as f:
        f.write("%s\t%s\t%d\n" % (flat(tab), flat(text), int(time.time() if now is None else now)))


def parse(line):
    """(tab, text, seconds or None) of one line, either format."""
    tab, _, rest = line.rstrip("\n").partition("\t")
    text, sep, t = rest.rpartition("\t")
    if sep and t.isdigit():
        return tab, text, int(t)
    return tab, rest, None


def since(t, p=None):
    """[(seconds, tab, text)] written after t, oldest first."""
    out = []
    try:
        with open(p or path(), errors="replace") as f:
            for l in f:
                tab, text, when = parse(l)
                if when is not None and when > t and text.strip():
                    out.append((when, tab.strip(), text.strip()))
    except OSError:
        pass
    return out
