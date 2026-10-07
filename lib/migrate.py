"""Profiles that grow with the deck: `phosphor migrate`.

A change to the shipped defaults never reaches a profile that already
exists (gen never rewrites it). When a shape changes, the change is a step
here instead: `version` in [deck] says which steps a profile has had (none
means 1), and migrate shows each pending step as a diff, then writes them
all at once through deckconf.write_profile (one .bak). doctor, gen, update
and the DECK tab say when one is pending.

A step is (version it brings the profile to, what it does, fn): fn takes
the profile's text and returns it changed, or unchanged when it doesn't
apply. A profile written by `phosphor init` already has the current
version, so no step ever runs on it."""
import difflib, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *
import deckconf

CURRENT = 2

def version(prof):
    """The profile's version: [deck] version, 1 without one."""
    v = ((prof or {}).get("deck") or {}).get("version", 1)
    return v if isinstance(v, int) and not isinstance(v, bool) else 1

def _parse(text):
    return deckconf.tomllib.loads(text)

# ── the steps ─────────────────────────────────────────────────
def two_panes(prof):
    """The tab that still has the key guide beside the panel (every profile
    before the panel took the whole tab): its name, or None."""
    for t in (prof or {}).get("tabs", []):
        cmds = [(q.get("cmd") or "").strip() for q in t.get("panes") or []]
        if sorted(cmds) == ["phosphor keys", "phosphor panel"]:
            return t.get("name")
    return None

def one_pane(text):
    """1.2.5: the panel takes the whole DECK tab, its key guide is ? in it."""
    import keep
    name = two_panes(_parse(text))
    return keep.put(text, name, keep.block(name, [{"cmd": "phosphor panel"}])) if name else text

def tts_table(text):
    """[deck] tts = true was the first place of [tts] enabled."""
    prof = _parse(text)
    deck = prof.get("deck") or {}
    if "tts" not in deck:
        return text
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == "[deck]"), None)
    if start is None:
        return text
    end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
    at = next((i for i in range(start + 1, end) if re.match(r"\s*tts\s*=", lines[i])), None)
    if at is None:
        return text
    del lines[at]
    text = "\n".join(lines)
    if "enabled" not in (prof.get("tts") or {}):
        text = deckconf.with_key(text, "tts", "enabled", "true" if deck["tts"] is True else "false")
    return text

STEPS = [(2, "the DECK tab in one pane: the panel takes the whole tab, its keys are ? in it", one_pane),
         (2, "[deck] tts moves to [tts] enabled, where it's documented", tts_table)]

# ── planning ──────────────────────────────────────────────────
def plan(text):
    """(steps, new text, version): steps is [(what, before, after)] for each
    step that changes something; the new text also carries version =
    CURRENT. A profile newer than this phosphor is left as it is."""
    ver = version(_parse(text))
    out, cur = [], text
    for to, what, fn in STEPS:
        if to <= ver:
            continue
        nxt = fn(cur)
        if nxt != cur:
            out.append((what, cur, nxt)); cur = nxt
    if ver < CURRENT:
        cur = deckconf.with_key(cur, "deck", "version", str(CURRENT))
    return out, cur, ver

def pending():
    """What migrate would change in the profile, as a list of what each step
    does; [] when nothing (or no profile, or one that doesn't parse: doctor
    says that on its own)."""
    if deckconf.example() or deckconf.tomllib is None:
        return []
    try:
        return [what for what, _, _ in plan(open(deckconf.path()).read())[0]]
    except Exception:
        return []

def newer():
    """The profile's version when a newer phosphor wrote it, else None."""
    prof = deckconf.load()[0]
    return version(prof) if prof and version(prof) > CURRENT else None

def diff(a, b):
    out = []
    for l in list(difflib.unified_diff(a.split("\n"), b.split("\n"), n=1, lineterm=""))[2:]:
        if l.startswith("@@"):
            out.append("  " + MUTE + "···" + RST)
        elif l.startswith("+"):
            out.append("  " + PH + l + RST)
        elif l.startswith("-"):
            out.append("  " + RED + l + RST)
        else:
            out.append("  " + DIM + l + RST)
    return out

def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv or "-n" in argv
    if deckconf.example():
        print("  there's no profile yet: phosphor init"); return 1
    if deckconf.tomllib is None:
        print("  no TOML parser: pip install --user tomli"); return 1
    p = deckconf.path()
    text = open(p).read()
    try:
        steps, new, ver = plan(text)
    except Exception as e:
        print(row(BAD, "profile", "doesn't parse: %s" % str(e)[:60], note="fix it, then migrate")); return 1
    print()
    print(BLOOM + "  phosphor migrate" + RST + DIM + ("  (dry-run)" if dry else "") + RST)
    print(DIM + "  " + p.replace(os.path.expanduser("~"), "~", 1) + ", version %d" % ver + RST)
    if ver > CURRENT:
        print(row(WARN, "profile", "version %d: a newer phosphor wrote it" % ver,
                  note="this one knows up to %d: phosphor update" % CURRENT))
        return 1
    if ver == CURRENT:
        print(row(OK, "profile", "up to date, nothing to migrate")); return 0
    for what, a, b in steps:
        print("\n" + rule(what))
        for l in diff(a, b):
            print(l)
    print("\n" + rule("version"))
    if not steps:
        print("  " + DIM + "nothing to change in this profile; only its version is written" + RST)
    print("  " + PH + "+version = %d" % CURRENT + RST + DIM + "   in [deck]" + RST)
    print()
    if dry:
        return 0
    from init import yes
    if not yes("write it into your profile? (a backup is kept)", True):
        return 0
    err = deckconf.write_profile(new, lambda prof: version(prof) == CURRENT, expect=text, p=p)
    if err:
        print(row(BAD, "not written", err)); return 1
    print(row(OK, "written", p.replace(os.path.expanduser("~"), "~", 1), note="backup: deck.toml.bak"))
    if steps:
        print("  " + DIM + "it shows after phosphor gen && phosphor restart (f in the DECK tab)" + RST)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
