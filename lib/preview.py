"""What a pane will look like before it's placed: the real size of the
cell a program or a card goes into, and a small map of a layout's shape
with what's in each cell so far.

A shape is a tree as newtab.SHAPES builds it: {"split": "cols"|"rows",
"panes": [...]}, with each cell's number at a leaf. zellij splits a tab
evenly and every pane keeps a frame, so a cell's program sees its share
of the tab less a column each side and a row above and below.
"""
import os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import *

FRAME = 2       # a pane's frame: a column each side, a row above and below


def cells(tree, w, h, x=0, y=0):
    """{cell: (x, y, w, h)}: the tree's leaves laid over w x h, each split
    in equal parts."""
    if not isinstance(tree, dict):
        return {tree: (x, y, w, h)}
    kids, out = tree["panes"], {}
    for i, k in enumerate(kids):
        if tree.get("split") == "rows":
            a, b = h * i // len(kids), h * (i + 1) // len(kids)
            out.update(cells(k, w, b - a, x, y + a))
        else:
            a, b = w * i // len(kids), w * (i + 1) // len(kids)
            out.update(cells(k, b - a, h, x + a, y))
    return out


def tab_size():
    """The tab a new layout splits: this pane (the + menu's, alone in its
    tab) with its frame back."""
    c, r = shutil.get_terminal_size((80, 24))
    return c + FRAME, r + FRAME


def inside(tree, cell, size=None):
    """(columns, rows) the program in that cell will have."""
    _, _, w, h = cells(tree, *(size or tab_size()))[cell]
    return max(1, w - FRAME), max(1, h - FRAME)


def shape_map(tree, labels, current, w, h, size=None):
    """The shape drawn w x h: a box per cell with what's in it so far
    (labels: {cell: text}), the one being picked bright with its real
    size. Its lines, each exactly w wide, as many as keep the tab's
    proportions (up to h)."""
    tw, th = size or tab_size()
    h = max(min(h, 4), min(h, round(w * th / tw)))
    chars = [[" "] * w for _ in range(h)]
    color = [[RULE] * w for _ in range(h)]

    def put(x, y, s, c):
        for i, ch in enumerate(s):
            if 0 <= y < h and 0 <= x + i < w:
                chars[y][x + i], color[y][x + i] = ch, c

    for n, (x, y, cw, ch) in sorted(cells(tree, w, h).items()):
        if cw < 3 or ch < 2:
            continue
        frame = AMB if n == current else RULE
        put(x, y, "┌" + "─" * (cw - 2) + "┐", frame)
        for r in range(y + 1, y + ch - 1):
            put(x, r, "│", frame); put(x + cw - 1, r, "│", frame)
        put(x, y + ch - 1, "└" + "─" * (cw - 2) + "┘", frame)
        text = labels.get(n) or ("?" if n == current else "")
        put(x + 1, y + 1, cut(text, cw - 2), BLOOM if n == current else FG)
        if n == current and ch >= 4:
            put(x + 1, y + 2, cut("%d×%d" % inside(tree, n, size), cw - 2), DIM)
    out = []
    for r in range(h):
        line, last = "", None
        for ch, c in zip(chars[r], color[r]):
            if c != last:
                line, last = line + c, c
            line += ch
        out.append(line + RST)
    return out


def beside(left, right, lw):
    """Two columns of lines: left cut and padded to lw, a space, right."""
    n = max(len(left), len(right))
    left, right = left + [""] * (n - len(left)), right + [""] * (n - len(right))
    return [pad(vcut(a, lw), lw) + " " + b for a, b in zip(left, right)]
