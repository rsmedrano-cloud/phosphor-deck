#!/usr/bin/env python3
"""The notebook's changes touch only the note they're meant for.

    python3 tests/notes-check.py

Archive, restore, mark done, edit and delete for good, on a scratch notebook.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import notes

fail = []
def check(what, cond):
    if not cond: fail.append(what)

d = tempfile.mkdtemp()
p = os.path.join(d, "notes.md")
open(p, "w").write(notes.PREAMBLE
    + "## 2026-09-10 10:00 · idea · claude · An index of AI chats\n\n- one line per machine\n\n"
    + "## 2026-09-11 10:00 · todo · me · Buy cables\n\n"
    + "## 2026-09-12 10:00 · note · me · Third\n\n")
first, todo, third = notes.read(p)[1]

check("three entries", len(notes.entries(p)) == 3)
check("newest first", notes.entries(p)[0]["title"] == "Third")

check("archive", notes.archive(p, todo, done=True))
check("archived is gone", [e["title"] for e in notes.entries(p)] == ["Third", "An index of AI chats"])
check("in the archive as done", notes.entries(notes.archive_of(p))[0]["kind"] == "done")
check("archive twice fails", not notes.archive(p, todo))

check("undo brings it back", notes.restore(p) == "Buy cables")
check("back in its place, as a todo", [(e["title"], e["kind"]) for e in notes.entries(p)]
      == [("Third", "note"), ("Buy cables", "todo"), ("An index of AI chats", "idea")])
check("archive empty again", notes.entries(notes.archive_of(p)) == [])
check("undo with nothing archived", notes.restore(p) is None)

new = notes.edited(first, "An index of AI conversations\n\n- one line per machine\n- a tap enters", "me")
check("edit marks someone else's note", notes.parse(new)["by"] == "claude, edited by me")
check("edit saves", notes.replace(p, first, new))
e = notes.entries(p)[-1]
check("edited title and body", e["title"] == "An index of AI conversations" and len(e["body"]) == 2)
check("no mark twice", notes.parse(notes.edited(new, "Again", "me"))["by"] == "claude, edited by me")
check("unchanged stays as it was", notes.edited(third, "Third\n", "me") == third)
check("an empty title is refused", notes.edited(third, "\n\n", "me") is None)
check("my own note isn't marked", notes.parse(notes.edited(third, "3rd", "me"))["by"] == "me")

notes.append(p, "note", "me", "Late append")
check("a stale edit isn't saved", not notes.replace(p, first, "## x"))
check("appends survive rewrites", notes.entries(p)[0]["title"] == "Late append")

third = [b for b in notes.read(p)[1] if "Third" in b][0]
notes.archive(p, third)
check("delete for good", notes.forget(p, third) and notes.entries(notes.archive_of(p)) == [])
check("the preamble stays", open(p).read().startswith("# Phosphor notes"))

on = {k for k, _, ok in notes.actions(notes.entries(p)[1]) if ok}
check("todo offers done", "x" in on and "e" in on and "w" in on)
check("same keys with or without a note", [a[0] for a in notes.actions(None)]
      == [a[0] for a in notes.actions(notes.entries(p)[1])])
check("nothing picked: only what needs no note", {k for k, _, ok in notes.actions(None) if ok} == set("atiuf/"))
lines, spots = notes.footer(notes.actions(None), 20)
check("footer wraps to the width", all(notes.vlen(l) <= 20 for l in lines) and len(lines) > 1)

# where a note was taken from
notes.append(p, "todo", "me", "Disk almost full", "", "SYS")
sys_note = notes.entries(p)[0]
check("the tab is in the header", "· me @SYS · Disk almost full" in open(p).read())
check("the tab parses apart from the author", (sys_note["by"], sys_note["tab"]) == ("me", "SYS"))
check("notes without a tab have none", notes.entries(p)[1]["tab"] == "")
check("only that tab's notes", [e["title"] for e in notes.entries(p, "SYS")] == ["Disk almost full"])
check("the tabs notes came from", notes.tabs_in(p) == ["SYS"])
moved = notes.edited(sys_note["raw"], "Disk almost full on nas", "claude")
check("an edit keeps the tab", (notes.parse(moved)["tab"], notes.parse(moved)["by"]) == ("SYS", "me, edited by claude"))
check("done keeps the tab", notes.parse(notes.rekind(sys_note["raw"], kind="done"))["tab"] == "SYS")
check("a tab name can't break the header", notes.parse(notes.header("2026-09-16 10:00", "note", "me", "t", "A · B @C"))["tab"] == "A   B  C")

# search (/): a filter over what entries() already parsed, no new I/O
e = {"title": "Buy cables", "body": "for the rack", "by": "me", "tab": "SYS"}
check("matches the title", notes.matches(e, "cables"))
check("matches the body", notes.matches(e, "the rack"))
check("matches the author, case-insensitive", notes.matches(e, "ME"))
check("matches the tab", notes.matches(e, "sys"))
check("no match", not notes.matches(e, "nope"))
check("always in the key guide, even with nothing picked", "/" in {k for k, _, ok in notes.actions(None) if ok})

# writing a note: what a phone keyboard and a narrow screen send
def type_in(*chunks):
    lines, done, pasting = [""], None, False
    for c in chunks:
        toks, pasting = notes.tokens(c, pasting)
        for t in toks:
            lines, done = notes.typed(lines, t)
            if done: return lines, done
    return lines, done

check("whole words at once keep every letter",
      type_in("thoughtwork", "\r", "prestar atencion", "\r", "durante shift", "\r", "\r")
      == (["thoughtwork", "prestar atencion", "durante shift"], "save"))
long = "una nota mucho mas larga que el ancho de la pantalla del telefono, sigue y sigue"
check("a line wider than the screen is saved whole", type_in(long, "\r", "\r") == ([long], "save"))
check("backspace across the wrap", type_in(long, "\x7f" * 40, "!\r\r") == ([long[:-40] + "!"], "save"))
check("backspace on an empty line goes back to the one above",
      type_in("uno\r", "\x7f", "s\r\r") == (["unos"], "save"))
check("ñ and accents", type_in("atención ñandú\r\r") == (["atención ñandú"], "save"))
check("a paste keeps its blank lines and doesn't save",
      type_in("\x1b[200~uno\n\ndos\x1b[201~")[1] is None
      and type_in("\x1b[200~uno\n\ndos\x1b[201~", "\r\r")[0] == ["uno", "dos"])
check("Ctrl-c cancels", type_in("algo", "\x03")[1] == "cancel")
check("arrows and a tap's release don't become text", type_in("a\x1b[A\x1b[<0;5;6mb\r\r") == (["ab"], "save"))
check("Enter on nothing saves nothing", type_in("\r")[0] == [""])
out, row, col = notes.draw_note("todo", "COMMS", [long, ""], 40)
check("the drawn note fits the width", all(notes.vlen(l) <= 40 for l in out))
check("the hint is said once", sum("saves" in notes.STRIP.sub("", l) for l in out) == 2)

if fail:
    print("FAIL: " + "; ".join(fail)); sys.exit(1)
print("ok")
