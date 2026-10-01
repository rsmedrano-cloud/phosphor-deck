"""Draws a bitmap face (see `phosphor face --bitmap`) at any size.

Pure Python, no imaging library: the face is a small grid of tones kept in
a JSON, scaled to the pane on the fly and drawn with half blocks (one text
cell = two stacked pixels), in the colors of the deck's theme. The amber
lights on the helmet are their own layer: they pulse, and turn red on an
alert.
"""
import math, random

TONES, ACCENTS = "0123456789abcdef", "ghijklmn"

def decode(rows):
    """Rows of TONES/ACCENTS -> (tone, accent) grids, both floats 0..1."""
    tone, acc = [], []
    for r in rows:
        t, a = [], []
        for ch in r:
            i = TONES.find(ch)
            if i >= 0:
                t.append(i / 15.0); a.append(0.0)
            else:
                j = ACCENTS.find(ch)
                t.append(0.0); a.append(0.35 + 0.65 * max(0, j) / 7.0)
        tone.append(t); acc.append(a)
    return tone, acc

def fit(sw, sh, cols, rows):
    """Pixel size the picture takes in a cols x rows pane (2 pixels per row)."""
    s = min(cols / sw, rows * 2 / sh)
    ow = max(1, int(sw * s)); oh = max(2, int(sh * s))
    return ow, oh - oh % 2

def scale(grid, ow, oh, thresh=None):
    """Box-average a grid to ow x oh."""
    sh, sw = len(grid), len(grid[0])
    out = []
    for y in range(oh):
        y0, y1 = y * sh / oh, (y + 1) * sh / oh
        ys = range(int(y0), max(int(y0) + 1, math.ceil(y1)))
        row = []
        for x in range(ow):
            x0, x1 = x * sw / ow, (x + 1) * sw / ow
            xs = range(int(x0), max(int(x0) + 1, math.ceil(x1)))
            tot = n = 0
            for yy in ys:
                if yy >= sh: continue
                g = grid[yy]
                for xx in xs:
                    if xx < sw:
                        tot += g[xx]; n += 1
            row.append(tot / n if n else 0.0)
        out.append(row)
    return out

def lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

class Face:
    """A bitmap face: frames are 'open', and optionally 'closed' (a blink)."""
    def __init__(self, bitmap, pal):
        self.src = {k: decode(v) for k, v in bitmap.items()}
        self.pal = pal
        self.cache = {}                       # (frame, ow, oh) -> scaled grids

    def size(self, cols, rows):
        h = next(iter(self.src.values()))[0]
        return fit(len(h[0]), len(h), cols, rows)

    def _scaled(self, frame, ow, oh):
        key = (frame, ow, oh)
        if key not in self.cache:
            tone, acc = self.src[frame]
            self.cache[key] = (scale(tone, ow, oh), scale(acc, ow, oh))
        return self.cache[key]

    def draw(self, cols, rows, frame="open", level=0, t=0.0, burst=0.0, sweep=None):
        """Lines of ANSI, each cols wide, rows of them (the picture centered).
        level: 0 ok, 1 warning, 2 alert. burst: 0..1 of glitch. sweep: a row
        (0..1 of the height) lit by the scanline, or None."""
        if frame not in self.src: frame = "open"
        ow, oh = self.size(cols, rows)
        tone, acc = self._scaled(frame, ow, oh)
        p = self.pal
        bg, ink, dim, hi = p["bg"], p["fg"], p["mute"], p["bloom"]
        paper = sum(bg) > 384                   # dark ink on white: the picture inverts
        if paper:
            ramp = lambda v: lerp(ink, bg, v)
        else:
            ramp = lambda v: lerp(bg, dim, v / 0.55) if v < 0.55 else lerp(dim, ink, (v - 0.55) / 0.45)
        light = (p["warn"], p["warn"], p["bad"])[min(level, 2)]
        speed = (1.6, 3.0, 7.0)[min(level, 2)]
        pulse = 0.62 + 0.38 * math.sin(t * speed)

        def px(x, y):
            v = tone[y][x]
            if sweep is not None and abs(y / max(1, oh - 1) - sweep) < 0.025:
                v = min(1.0, v + 0.28)
            c = ramp(v)
            a = acc[y][x]
            if a > 0.05:
                c = lerp(c, lerp(bg, light, min(1.0, a * pulse * 1.25)), min(1.0, a * 1.4))
            return c

        pad_x = (cols - ow) // 2
        pad_y = (rows - oh // 2) // 2
        blank = " " * cols
        out = [blank] * pad_y
        for cy in range(oh // 2):
            shift = 0
            if burst > 0 and random.random() < burst * 0.35:
                shift = random.randint(-3, 3)
            cells, last = [], None
            for x in range(ow):
                xx = min(ow - 1, max(0, x + shift))
                top, bot = px(xx, cy * 2), px(xx, cy * 2 + 1)
                if burst > 0 and random.random() < burst * 0.07:
                    n = random.random() * 0.9
                    top = bot = ramp(n)
                key = (tuple(int(v) for v in top), tuple(int(v) for v in bot))
                if key != last:
                    cells.append("\x1b[38;2;%d;%d;%d;48;2;%d;%d;%dm" % (key[0] + key[1]))
                    last = key
                cells.append("▀")
            out.append(" " * pad_x + "".join(cells) + "\x1b[0m" + " " * max(0, cols - pad_x - ow))
        out += [blank] * (rows - len(out))
        return out[:rows]
