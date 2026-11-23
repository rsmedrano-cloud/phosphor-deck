# Keys

zellij runs in **locked mode**: every key goes to the program in the pane,
except these.

<!-- keys:_deck -->

## Editing a tab

**Alt-r** (on a phone, the **EDIT** key) opens the whole tab as a map: a box
for each pane, with its number, what runs in it and its size (`55%`, `auto`,
`5 rows`). The tab doesn't change until you save. Nothing needs a zellij key.

Pick a pane by tapping it, with its number (1 to 9), the arrows or Tab. It
starts on the pane you were in when you pressed Alt-r. Every action is a key
and a button along the bottom, so a click or a tap works too:

- **+** / **-** make the pane bigger or smaller, 10% at a time. Its neighbour
  takes or gives the difference. A row of cards changes a row at a time. Never
  under 10% or over 90%.
- **b** splits below, **v** splits beside. The new pane is a shell, and it is
  selected.
- **r** swaps the pane's program: the + menu, the store apps, or cards.
- **c** on a row of cards changes its cards in the gallery. On any other pane
  it adds a row of cards under it.
- **x** closes the pane. Its space goes to the pane before it. The only pane
  can't be closed.

The strip at the top stays on screen: **s** save, **d** put back, **Esc**
cancel. The line under it says what changed, in words: `sleep 602: 45% → 50%`,
`panes: 2 → 3`.

- **s** writes the tab into your profile (a `deck.toml.bak` first), runs gen
  and reloads the tab as you drew it.
- **d** reloads the tab the way your profile has it.
- If a reload would lose something (a shell or an editor, the same thing
  `phosphor apply` asks about), the first **s** or **d** says what, and a
  second press does it.
- **Esc** with unsaved changes asks for a second Esc, then leaves the tab
  exactly as it was.

Tabs are locked: no pane is added or closed by accident. Dragging a border
still resizes a pane live, because zellij can't lock that. `phosphor restart`
(or **d** in the edit screen) brings back the sizes your profile has.

A tab that isn't in the profile yet (opened with +) is added when you save,
and it has no **d**. A tab from `tabs.d` (see profile) has no **s**: the
screen names the file instead, since saving there would fork it from whoever
you got it from. **d** still works there.

## Your own keys

Every deck key can be changed: `phosphor shortcuts` (or **c** in the DECK
tab) lists them; pick one, press the new key, and it works right away. It
warns when the key is taken by another deck key or by a tool (matterhorn,
the shell). Backspace turns one off. A key the deck already uses never
reaches that screen: free it first.

They're kept in `[keys]` in your profile (see profile), so an update never
resets them. `phosphor gen` writes them into zellij's config.kdl between two
marker lines and touches nothing else there: binds of your own can go
anywhere outside the markers. A config.kdl of your own without the markers
is left alone; `phosphor shortcuts --kdl` prints the block to paste inside
its `keybinds { }`.

The phone kit's EDIT, ZOOM and EXIT keys send whatever `[keys]` says (run the
kit again after changing them). With the key bar on, EDIT is on the bar instead
(see the key bar, below).

## Esc and q

Every screen of the deck's own (the DECK tab, FLEET, the panels, NOTES, the
menus) takes these two the same way:

- **Esc** goes back one step: it drops a pick, a filter or a search, leaves
  a page for its list, gives the tab back to a zoomed pane. With nothing
  left to go back from, it closes a screen you opened from somewhere (a
  card, a key of the DECK tab, the `+` menu, a shell) and you're back
  there. A screen the key bar opens over a pane (glance, MIC, ASK, NOTE, EDIT)
  says `Esc: back to <pane> (still running)` on its first line; Esc gives
  you the pane back, and it kept running. A pane of your tab stays where
  it is: Esc never closes it.
- **q** closes what you're looking at: a page goes back to its list, a
  picker to the step before it, a panel ends. A pane of your tab then
  asks, like any program that ends (below): Enter opens it again.
- **?** lists the keys of the screen you're on, the ones its bar doesn't
  show too; q goes back to it.
- While you type (a filter, a search, a note), q is a letter and Esc
  cancels the typing. At a y/n, Esc and q are no; in a menu with a
  "back" or "quit", they pick it.
- **Ctrl-C** stops the program in front of you. In a screen a card
  opened, that's the screen: you're back on the cards, which stay.

The few screens that pass every key on are the exception: a mirror of
another pane, a shell, a tool like yazi or btop, which keep their own.

## When a program ends

Every program runs through `phosphor run`. When it ends (`exit`, `q`, a
crash) the pane doesn't vanish or quietly restart: it says so in color and
asks. **Enter** opens it again, **x** closes the tab. A mistyped exit costs
one key. In ssh tabs a dropped link reconnects by itself; a program that isn't
installed says so. If that tab is kept in your profile (so it comes back
after every restart) and this was its last program, a third choice shows:
**f** closes it and forgets it, out of the profile for good. `phosphor tabs`
does the same for any kept tab. A program that froze (the pane changed size and it didn't
answer or do anything for 20 seconds) is closed and the pane says "stopped
responding": Enter opens it again. Every one of these choices is a row of
its own, so a tap answers it too, on a screen with no keyboard.

## Tapping

Tap a tab to switch, a pane to focus it; `+` in the tab bar opens the new-tab
menu, and its last row ("close this tab") takes the tab back out if you
opened it by mistake. On phones, taps go to the deck, so the keyboard needs its own key (the
phone kit adds KEYBOARD, EDIT, ZOOM and EXIT; with the key bar, EDIT is on the bar).

A panel's title ends in ⤢: a tap there zooms its pane, the same as Alt-z,
and Esc gives the tab back. A panel in a pane too short for it (under six
rows: SYS's row of cards, a phone's split) draws a summary of one to three
lines under its title instead, and a tap anywhere on it zooms: the whole
panel, with its keys, is one tap away.

The DECK tab has every phosphor action (a key or a tap each), and `?` there
lists the keys of every installed tool. Its second line, when nothing more
urgent wants it, is a "did you know?": one thing the deck does and where it
is, the ones you've never used first, a new one every ten minutes; a tap on
it does it when it names a key of the DECK tab.

## The key bar

With `[bar]` on (the default for new decks, see profile), the bottom two rows
of every tab have five keys and the fleet light. With `[voice]` on, MIC makes six:
it comes after HOME, and its shortcut is Alt-m. Each key shows its glyph over
its word; where there's room, the top row also has the shortcut:

     ⌂ Alt-1   ? Alt-q   ✎ Alt-j   ⇲ Alt-r   ⤢ Alt-z        ●
      HOME       ASK      NOTE      EDIT      ZOOM          2

With voice on:

     ⌂ Alt-1   ◉ Alt-m   ? Alt-q   ✎ Alt-j   ⇲ Alt-r   ⤢ Alt-z        ●
      HOME       MIC       ASK      NOTE      EDIT      ZOOM          2

Narrower, only the glyph over the word:

      ⌂      ?     ✎      ⇲      ⤢       ●
     HOME   ASK   NOTE   EDIT   ZOOM     2

A tap on either row of a key runs it the way its Alt key does, on the pane you
were in before you tapped. HOME goes to the first tab. The light opens
`phosphor glance` in place of the pane; `q` or Esc gives the pane back.

From the keyboard: Alt-Down moves into the bar. Left and Right pick a key, Enter
runs it, Esc or q gives the focus back.

The shortcuts shown come from `[keys]`: a key turned off shows none, and HOME
shows the tab prefix and 1.

While a pane is zoomed, the bar is hidden. Alt-z (ZOOM on a phone's extra keys,
or Esc in a phosphor panel) gives the tab back.

Saving an edited tab (Alt-r) never writes the bar into the tab's panes. A tab
whose last pane closes goes with its bar; it never stays as a bar alone.

Known limit, not checked yet: two screens on the same tab at once (a phone and
a desktop). Which one a tap moves the focus back to is zellij's call.
