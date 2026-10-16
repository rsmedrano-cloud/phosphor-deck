"""A small terminal screen in memory, for a screen too slow to get a
program's output as it comes.

A program run for an e-ink panel writes its redraws here, not to the
panel: lines() is what the screen would show now (no color, inverse
kept: it's how a selection shows in mono), and the caller sends the
panel only the lines that changed since the last paint (ui.paint), as
often as the panel can take them. Ten redraws in a second reach it as
one.

It knows what the deck's own screens and a shell write -- cursor moves,
erases, scroll regions, insert/delete lines, inverse -- and drops
everything else (colors, titles, mouse modes) without a trace.
"""
import codecs, unicodedata

INV, RST = "\x1b[7m", "\x1b[0m"


def width(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in "WF" else 1


class Screen:
    def __init__(self, cols, rows):
        self.dec = codecs.getincrementaldecoder("utf-8")("replace")
        self.state, self.buf = "text", ""
        self.resize(cols, rows, clear=True)

    def resize(self, cols, rows, clear=False):
        cols, rows = max(1, cols), max(1, rows)
        old = None if clear else self.grid
        self.cols, self.rows = cols, rows
        self.grid = [self.blank() for _ in range(rows)]
        if old:                         # keep the bottom of what was there, like a terminal
            for i, line in enumerate(old[-rows:]):
                self.grid[i][:min(cols, len(line))] = line[:cols]
        self.x = min(getattr(self, "x", 0), cols - 1)
        self.y = min(getattr(self, "y", 0), rows - 1)
        self.top, self.bot = 0, rows - 1
        self.inv, self.wrap, self.saved = False, False, (0, 0)

    def blank(self):
        return [(" ", False) for _ in range(self.cols)]

    # -- feeding ----------------------------------------------------------

    def feed(self, data):
        text = self.dec.decode(data) if isinstance(data, bytes) else data
        for ch in text:
            self.step(ch)

    def step(self, ch):
        st = self.state
        if st == "text":
            if ch == "\x1b":
                self.state, self.buf = "esc", ""
            elif ch < " " or ch == "\x7f":
                self.control(ch)
            else:
                self.put(ch)
        elif st == "esc":
            if ch == "[":
                self.state, self.buf = "csi", ""
            elif ch == "]":
                self.state = "osc"
            elif ch in "()*+#":
                self.state = "charset"
            else:
                self.state = "text"
                self.escape(ch)
        elif st == "charset":
            self.state = "text"
        elif st == "osc":                       # a title and the like: up to BEL or ST
            if ch == "\x07":
                self.state = "text"
            elif ch == "\x1b":
                self.state = "osc-esc"
        elif st == "osc-esc":
            self.state = "text" if ch == "\\" else "osc"
        elif st == "csi":
            if "@" <= ch <= "~":
                self.state = "text"
                self.csi(self.buf, ch)
            elif len(self.buf) < 64:
                self.buf += ch
            else:
                self.state = "text"

    def control(self, ch):
        if ch == "\r":
            self.x, self.wrap = 0, False
        elif ch in "\n\x0b\x0c":
            self.index()
        elif ch == "\b":
            self.x, self.wrap = max(0, self.x - 1), False
        elif ch == "\t":
            self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)

    def escape(self, ch):
        if ch == "7":
            self.saved = (self.x, self.y)
        elif ch == "8":
            self.x, self.y = self.saved
        elif ch == "D":
            self.index()
        elif ch == "E":
            self.x = 0; self.index()
        elif ch == "M":
            if self.y == self.top:
                self.scroll(-1)
            else:
                self.y = max(0, self.y - 1)
        elif ch == "c":
            self.resize(self.cols, self.rows, clear=True)

    def index(self):
        self.wrap = False
        if self.y == self.bot:
            self.scroll(1)
        else:
            self.y = min(self.rows - 1, self.y + 1)

    def scroll(self, n):
        """n lines up (n < 0: down) inside the scroll region."""
        region = self.grid[self.top:self.bot + 1]
        h = len(region)
        n = max(-h, min(h, n))
        if n > 0:
            region = region[n:] + [self.blank() for _ in range(n)]
        elif n < 0:
            region = [self.blank() for _ in range(-n)] + region[:h + n]
        self.grid[self.top:self.bot + 1] = region

    def put(self, ch):
        w = width(ch)
        if w == 0:
            return
        if self.wrap:
            self.x = 0; self.index()
        if w == 2 and self.x == self.cols - 1:
            self.grid[self.y][self.x] = (" ", self.inv)
            self.x = 0; self.index()
        row = self.grid[self.y]
        row[self.x] = (ch, self.inv)
        if w == 2 and self.x + 1 < self.cols:
            row[self.x + 1] = ("", self.inv)     # the right half of a wide char
        if self.x + w >= self.cols:
            self.x, self.wrap = self.cols - 1, True
        else:
            self.x += w

    def csi(self, buf, final):
        private = buf[:1] in "?>=<" and buf[:1] != ""
        args = buf[1:] if private else buf
        ps = []
        for a in args.split(";"):
            try: ps.append(int(a.split(":")[0]))
            except ValueError: ps.append(None)
        def p(i, d=1):
            v = ps[i] if i < len(ps) else None
            return d if v is None or (v == 0 and d == 1) else v
        if private:
            if final in "hl" and buf.startswith("?") and any(m in ps for m in (47, 1047, 1049)):
                self.grid = [self.blank() for _ in range(self.rows)]     # the alternate screen, in or out
                self.x = self.y = 0
            return
        self.wrap = False
        if final == "A":
            self.y = max(self.top if self.y >= self.top else 0, self.y - p(0))
        elif final == "B":
            self.y = min(self.bot if self.y <= self.bot else self.rows - 1, self.y + p(0))
        elif final in "Ca":
            self.x = min(self.cols - 1, self.x + p(0))
        elif final == "D":
            self.x = max(0, self.x - p(0))
        elif final == "E":
            self.x, self.y = 0, min(self.rows - 1, self.y + p(0))
        elif final == "F":
            self.x, self.y = 0, max(0, self.y - p(0))
        elif final in "G`":
            self.x = min(self.cols - 1, p(0) - 1)
        elif final in "Hf":
            self.y = min(self.rows - 1, p(0) - 1)
            self.x = min(self.cols - 1, p(1) - 1)
        elif final == "d":
            self.y = min(self.rows - 1, p(0) - 1)
        elif final == "J":
            self.erase_display(p(0, 0))
        elif final == "K":
            self.erase_line(p(0, 0))
        elif final == "X":
            row = self.grid[self.y]
            for i in range(self.x, min(self.cols, self.x + p(0))):
                row[i] = (" ", False)
        elif final == "P":
            row = self.grid[self.y]
            n = min(p(0), self.cols - self.x)
            del row[self.x:self.x + n]
            row += [(" ", False)] * n
        elif final == "@":
            row = self.grid[self.y]
            n = min(p(0), self.cols - self.x)
            row[self.x:self.x] = [(" ", False)] * n
            del row[self.cols:]
        elif final in "LM":
            if self.top <= self.y <= self.bot:
                top = self.top
                self.top = self.y
                self.scroll(-p(0) if final == "L" else p(0))
                self.top = top
        elif final == "S":
            self.scroll(p(0))
        elif final == "T":
            self.scroll(-p(0))
        elif final == "r":
            top, bot = p(0) - 1, (ps[1] if len(ps) > 1 and ps[1] else self.rows) - 1
            if 0 <= top < bot < self.rows:
                self.top, self.bot = top, bot
            else:
                self.top, self.bot = 0, self.rows - 1
            self.x = self.y = 0
        elif final == "s":
            self.saved = (self.x, self.y)
        elif final == "u":
            self.x, self.y = self.saved
        elif final == "m":
            self.sgr([0] if not ps else [v or 0 for v in ps])

    def sgr(self, ps):
        for v in ps:
            if v == 0 or v == 27:
                self.inv = False
            elif v == 7:
                self.inv = True

    def erase_display(self, how):
        if how == 0:
            self.erase_line(0)
            for r in range(self.y + 1, self.rows):
                self.grid[r] = self.blank()
        elif how == 1:
            self.erase_line(1)
            for r in range(0, self.y):
                self.grid[r] = self.blank()
        else:
            self.grid = [self.blank() for _ in range(self.rows)]

    def erase_line(self, how):
        row = self.grid[self.y]
        if how == 0:
            span = range(self.x, self.cols)
        elif how == 1:
            span = range(0, self.x + 1)
        else:
            span = range(self.cols)
        for i in span:
            row[i] = (" ", False)

    # -- reading ----------------------------------------------------------

    def lines(self):
        """What the screen shows: one string per row, inverse runs kept,
        trailing blanks dropped."""
        out = []
        for row in self.grid:
            end = len(row)
            while end and row[end - 1] == (" ", False):
                end -= 1
            s, inv = [], False
            for ch, i in row[:end]:
                if i != inv:
                    s.append(INV if i else RST); inv = i
                s.append(ch)
            if inv:
                s.append(RST)
            out.append("".join(s))
        return out
