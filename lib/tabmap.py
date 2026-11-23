"""A tab as a map of its panes, and the changes Alt-r makes to it (#125).

The tab is its profile shape ([[tabs]]: panes, split, sizes) held as a
tree; nothing here talks to zellij. Alt-r's screen (lib/edit.py) draws it
with draw(), takes a key or a tap, changes the tree with one of these, and
only saving writes it into the profile and reloads the tab:

    resize(root, path, +1 / -1)    a pane bigger or smaller, in steps
    split(root, path, "rows")      a new pane below it ("cols": beside)
    close(root, path)              it goes, its space to its neighbours
    put(root, path, spec)          another program (or cards) in it

A path is the tuple of indices down to a pane; leaves(root) lists them in
the order panes get their numbers (1-9, then a-z).
"""
import copy, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ui import FG, DIM, RST, AMB, BLOOM, RULE, vcut

KEYS = "123456789abcdefghijklnoptuwyz"     # a pane's number; not the action keys (m q r s v x ...)
STEP = 10                                 # a percentage step
MIN, MAX = 10, 90

def root(specs, split=None):
    return {"split": split or "rows", "panes": copy.deepcopy(specs)}

def unroot(r, split=None):
    """(specs, split) back in profile shape; split stays as the tab had it
    (None for rows when it said nothing)."""
    s = r["split"]
    return copy.deepcopy(r["panes"]), (split if (split or "rows") == s else s)

def is_box(n):
    return isinstance(n, dict) and "panes" in n

def leaves(n, path=()):
    if not is_box(n):
        return [path]
    out = []
    for i, k in enumerate(n["panes"]):
        out += leaves(k, path + (i,))
    return out

def node(r, path):
    for i in path:
        r = r["panes"][i]
    return r

def parent(r, path):
    return node(r, path[:-1]), path[-1]

def label(s):
    if "dash" in s: return "cards: " + ", ".join(s["dash"]) if s["dash"] else "cards"
    if "ssh" in s: return "ssh " + s["ssh"]
    if not s.get("cmd"): return "shell"
    return " ".join([os.path.basename(s["cmd"])] + [str(a) for a in s.get("args", [])])

# ── sizes ─────────────────────────────────────────────────────
def _pct(s):
    return int(s[:-1]) if isinstance(s, str) and s.endswith("%") and s[:-1].isdigit() else None

def extents(kids, total, real, least=1):
    """How much of total (cells on screen) each kid takes along its split:
    "N%" that share, an int that many of the real tab's cells (scaled to
    total, never under least), the rest shared by the ones with no size."""
    got = []
    for k in kids:
        s = k.get("size") if isinstance(k, dict) else None
        if isinstance(s, int) and not isinstance(s, bool):
            got.append(max(least, round(s * total / max(1, real))))
        elif _pct(s) is not None:
            got.append(round(total * _pct(s) / 100))
        else:
            got.append(None)
    free = [i for i, g in enumerate(got) if g is None]
    rest = total - sum(g for g in got if g is not None)
    if free:
        if rest < least * len(free):           # sizes that don't leave room: equal parts
            return [total * (i + 1) // len(kids) - total * i // len(kids) for i in range(len(kids))]
        for j, i in enumerate(free):
            got[i] = rest * (j + 1) // len(free) - rest * j // len(free)
    else:
        got[-1] += rest                        # zellij gives the last one what's left over
    if any(g < 1 for g in got):
        return [total * (i + 1) // len(kids) - total * i // len(kids) for i in range(len(kids))]
    return got

def rects(r, w, h, real=None, x=0, y=0, path=()):
    """{path: (x, y, w, h)}: every pane of the tree laid over w x h with the
    sizes it has; real is the tab's own (columns, rows), for sizes in cells."""
    rw, rh = real or (w, h)
    if not is_box(r):
        return {path: (x, y, w, h)}
    rows = r.get("split", "rows") == "rows"
    kids = r["panes"]
    ext = extents(kids, h if rows else w, rh if rows else rw, 3 if rows else 6)
    out, at = {}, 0
    for i, (k, e) in enumerate(zip(kids, ext)):
        if rows:
            out.update(rects(k, w, e, (rw, rh * e // max(1, h)), x, y + at, path + (i,)))
        else:
            out.update(rects(k, e, h, (rw * e // max(1, w), rh), x + at, y, path + (i,)))
        at += e
    return out

def bound(placed, prefix):
    """(x0, y0, x1, y1) around every pane under prefix."""
    got = [v for q, v in placed.items() if q[:len(prefix)] == prefix]
    return (min(x for x, _, _, _ in got), min(y for _, y, _, _ in got),
            max(x + w for x, _, w, _ in got), max(y + h for _, y, _, h in got))

def share(r, path, real):
    """The percentage of its row (or column) a pane has now, from the sizes,
    on a tab of real (columns, rows)."""
    if not path:
        return 100
    placed = rects(r, real[0], real[1], real)
    rows = parent(r, path)[0].get("split", "rows") == "rows"
    a, b = bound(placed, path), bound(placed, path[:-1])
    k = 1 if rows else 0
    return round(100 * (a[k + 2] - a[k]) / max(1, b[k + 2] - b[k]))

def size_text(s, rows):
    v = s.get("size")
    if isinstance(v, int) and not isinstance(v, bool):
        return "%d %s" % (v, ("row" if rows else "col") + ("" if v == 1 else "s"))
    return v or "auto"

def resize(r, path, d, real=(100, 30)):
    """The pane one step bigger (d=1) or smaller (d=-1) along its split; its
    neighbour takes or gives the difference. A reason if it can't, else None."""
    while path and len(parent(r, path)[0]["panes"]) < 2:
        path = path[:-1]
    if not path:
        return "it's the only pane: it fills the tab"
    box, i = parent(r, path)
    kids = box["panes"]
    rows = box.get("split", "rows") == "rows"
    me = kids[i]
    s = me.get("size")
    if isinstance(s, int) and not isinstance(s, bool):   # a row of cards: a line (4 columns) at a time
        new = s + d * (1 if rows else 4)
        if new < 1:
            return "it's as small as it gets"
        me["size"] = new
        return None
    flex = [j for j in sorted(range(len(kids)), key=lambda j: (abs(j - i), j < i))
            if j != i and not isinstance(kids[j].get("size"), int)]
    if not flex:
        return "it takes what the others leave: make one of them smaller"
    now = share(r, path, real)
    others = sum(_pct(k.get("size")) or 0 for j, k in enumerate(kids) if j not in (i, flex[0]))
    step = (now // STEP + 1) * STEP if d > 0 else (-(-now // STEP) - 1) * STEP   # 45 → 50 or 40
    new = max(MIN, min(MAX, step, 100 - others - MIN))
    if (d > 0 and new <= now) or (d < 0 and new >= now):
        return "it's as %s as it gets" % ("big" if d > 0 else "small")
    me["size"] = "%d%%" % new
    kids[flex[0]].pop("size", None)
    return None

# ── panes in, out, swapped ────────────────────────────────────
def split(r, path, way, spec=None):
    """A new pane after this one, below it (way "rows") or beside it
    ("cols"): a shell unless spec says what. The new pane's path."""
    new = dict(spec or {"cmd": ""})
    if not path:                                # a tab of one pane is the root box itself
        path = (0,)
    box, i = parent(r, path)
    me = box["panes"][i]
    if box.get("split", "rows") == way:
        s = me.get("size")
        if "size" not in new:
            if _pct(s) is not None:            # half each
                half = _pct(s) // 2
                me["size"], new["size"] = "%d%%" % (_pct(s) - half), "%d%%" % half
            elif isinstance(s, int):
                new["size"] = s
        box["panes"].insert(i + 1, new)
        return path[:-1] + (i + 1,)
    inner = {k: v for k, v in me.items() if k != "size"}
    two = {"split": way, "panes": [inner, new]}
    if "size" in me:
        two["size"] = me["size"]
    box["panes"][i] = two
    return path + (1,)

def close(r, path):
    """Take the pane out; a box left with one pane becomes that pane. The
    path to select next (the pane that took its space), or a reason it
    can't go."""
    if len(leaves(r)) < 2:
        return "it's the only pane in the tab: put something else in it with r"
    box, i = parent(r, path)
    gone = box["panes"].pop(i)
    kids = box["panes"]
    j = i - 1 if i > 0 else 0                    # its space goes to the pane before it (or after)
    if _pct(gone.get("size")) is not None and _pct(kids[j].get("size")) is not None:
        kids[j]["size"] = "%d%%" % min(MAX, _pct(kids[j]["size"]) + _pct(gone["size"]))
    if all(k.get("size") is not None for k in kids):    # someone has to take what's left
        flex = sorted((n for n, k in enumerate(kids) if not isinstance(k.get("size"), int)),
                      key=lambda n: abs(n - j))
        if flex: kids[flex[0]].pop("size", None)
    at = path[:-1]
    to = at + (i - 1 if i > 0 else 0,)          # the pane that took its space is selected
    if len(kids) == 1:
        to = at
        only = kids[0]
        if at:                                  # the box becomes its one pane, at the box's size
            outer, k = parent(r, at)
            if "size" in box: only["size"] = box["size"]
            else: only.pop("size", None)
            outer["panes"][k] = only
        elif is_box(only):                      # the tab's one box is the tab's split
            r["split"], r["panes"] = only.get("split", "rows"), only["panes"]
        else:
            only.pop("size", None)
    left = leaves(r)
    return next((p for p in left if p[:len(to)] == to), left[0])

def put(r, path, spec):
    """Another program in the pane, at the size it had."""
    if not path:
        path = (0,)
    box, i = parent(r, path)
    old = box["panes"][i]
    new = {k: v for k, v in spec.items() if k != "size"}
    if "size" in old:
        new["size"] = old["size"]
    box["panes"][i] = new

# ── moving the selection ──────────────────────────────────────
def nearest(placed, cur, way):
    """The pane next to cur in that direction (up down left right), or cur."""
    x, y, w, h = placed[cur]
    cx, cy = x + w / 2, y + h / 2
    best, score = cur, None
    for p, (px, py, pw, ph) in placed.items():
        if p == cur: continue
        if way == "up" and py + ph > y: continue
        if way == "down" and py < y + h: continue
        if way == "left" and px + pw > x: continue
        if way == "right" and px < x + w: continue
        dx, dy = abs(px + pw / 2 - cx), abs(py + ph / 2 - cy)
        far = dy + dx / 2 if way in ("up", "down") else dx + dy / 2
        if score is None or far < score:
            best, score = p, far
    return best

# ── the map ───────────────────────────────────────────────────
def draw(r, sel, w, h, real=None):
    """The tab drawn w x h: a box per pane, its number, what runs in it and
    its size, the selected one bright. (lines, {path: (x, y, w, h)})."""
    placed = rects(r, w, h, real)
    order = leaves(r)
    chars = [[" "] * w for _ in range(h)]
    color = [[RULE] * w for _ in range(h)]

    def at(x, y, s, c):
        for i, ch in enumerate(s):
            if 0 <= y < h and 0 <= x + i < w:
                chars[y][x + i], color[y][x + i] = ch, c

    for p in order:
        x, y, cw, ch = placed[p]
        if cw < 3 or ch < 2:
            continue
        on = p == sel
        frame = AMB if on else RULE
        at(x, y, "┌" + "─" * (cw - 2) + "┐", frame)
        for row in range(y + 1, y + ch - 1):
            at(x, row, "│", frame); at(x + cw - 1, row, "│", frame)
        at(x, y + ch - 1, "└" + "─" * (cw - 2) + "┘", frame)
        n = order.index(p)
        key = KEYS[n] if n < len(KEYS) else "·"
        box, i = parent(r, p) if p else (r, 0)
        rows = box.get("split", "rows") == "rows"
        spec = node(r, p)
        inner = cw - 2
        size = size_text(spec, rows)
        if ch == 3:                             # no line of its own for the size
            at(x + 1, y + 1, vcut(("▶ " if on else "  ") + key + " " + label(spec) + " · " + size, inner),
               BLOOM if on else FG)
        elif ch > 3:
            at(x + 1, y + 1, vcut(("▶ " if on else "  ") + key + " " + label(spec), inner), BLOOM if on else FG)
        else:                                   # a two-line box: the number on its top border
            at(x + 1, y, vcut(" " + key + " " + label(spec) + " ", inner), BLOOM if on else FG)
        if ch >= 4:
            at(x + 3, y + 2, vcut(size, max(0, inner - 2)), DIM)
    out = []
    for row in range(h):
        line, last = "", None
        for c, col in zip(chars[row], color[row]):
            if col != last:
                line, last = line + col, col
            line += c
        out.append(line + RST)
    return out, placed
