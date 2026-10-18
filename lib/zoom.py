"""Zoom from inside a panel: what Alt-z does, with a tap.

A panel's title line ends in MARK; a tap on it makes the pane take the
whole tab (zellij's toggle-fullscreen, the same as Alt-z), Esc gives the
tab back. A pane too short for its panel (short(rows)) draws a summary of
one to three lines instead, and any tap on it zooms: the full panel is
one tap away, wherever the profile put it.

Outside zellij there's nothing to zoom: no mark, and Esc does what it
always did.
"""
import json, os

MARK = "⤢"
SHORT = 6          # a pane with fewer rows than this draws its summary
SUMMARY = 3        # at most this many lines of it


def here():
    """True inside a zellij pane, where zoom means something."""
    return bool(os.environ.get("ZELLIJ") and os.environ.get("ZELLIJ_PANE_ID"))


def short(rows):
    return rows < SHORT


def mark(line, w):
    """The title line with MARK in its last column but one (a line never
    fills a pane: zellij would wrap it), the line as it was outside
    zellij. Drawn w - 3 wide, it loses nothing."""
    if not here() or w < 6:
        return line
    from ui import vcut, pad, AMB, RST
    return pad(vcut(line, w - 3), w - 3) + " " + AMB + MARK + RST


def on_mark(x, y, w):
    """A tap at column x, row y (1-based) is on the mark of a line drawn by mark()."""
    return here() and w >= 6 and y == 1 and x >= w - 3


def zj(*a):
    import newtab
    return newtab.zj(*a)


def zoomed():
    """True when this pane is the one taking the whole tab."""
    if not here():
        return False
    try:
        me = int(os.environ["ZELLIJ_PANE_ID"])
        for p in json.loads(zj("list-panes", "-a", "-j") or "[]"):
            if p.get("id") == me and not p.get("is_plugin"):
                return bool(p.get("is_fullscreen"))
    except (ValueError, TypeError):
        pass
    return False


def toggle():
    """Zoom this pane, or give the tab back: Alt-z. A tap or a key reached
    it, so it's the focused pane, the one zellij toggles."""
    if here():
        zj("toggle-fullscreen")


def tapped():
    """True in a screen a card's tap opened: PHOSPHOR_CARD is "PID NAME" of
    the card that ran it (card.tap). Anything that screen starts in turn
    inherits the variable, but its parent isn't the card (crash_name in
    phosphor does the same with PHOSPHOR_RUN)."""
    pid, _, _ = os.environ.get("PHOSPHOR_CARD", "").partition(" ")
    return bool(pid) and pid == str(os.getppid())


def back():
    """Esc: give the tab back when zoomed. False when it wasn't (Esc then
    does what it did before), and in a screen a card's tap opened
    (PHOSPHOR_CARD): the card zoomed it, and gives it back once Esc ends
    that screen."""
    if tapped():
        return False
    if zoomed():
        toggle()
        return True
    return False
