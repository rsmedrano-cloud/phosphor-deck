# Keys

zellij runs in **locked mode**: every key goes to the program in the pane,
except these.

<!-- keys:_deck -->

## Editing a tab

Tabs are locked: no pane is added or closed by accident. To change one on
purpose, **Alt-r** (on a phone, the **EDIT** key). Every step works with a
key, a click or a tap: each action is a row of its own.

1. **start editing** unlocks the tab (a ✎ marks it in the tab bar). Resize
   by dragging a border, or Ctrl-n and the arrows; Ctrl-p n / x add and
   close panes.
2. **Alt-r** again shows what changed (`ctop → lazydocker`, `45% → 55%`) and
   what you can do with the pane under that screen:
   **s** save the tab into your profile · **d** put it back the way the
   profile has it · **r** swap the pane's program for anything the + menu or
   the store has, or for cards (**cards** opens the gallery: pick some,
   Enter puts them in the pane; beside the list, what's under the cursor
   at this pane's size; the first few times, its last row says what
   Enter does) · **b** / **v** split it (a new pane below / beside) ·
   **x** close it · **e** keep editing.

One thing zellij doesn't let us lock: dragging a border resizes a pane even
while the tab is locked. `phosphor restart` (or Alt-r, then d) brings back the
sizes your profile has.

A tab that isn't in the profile yet (opened with +) is added when you save.
A tab from `tabs.d` (see profile) has no **s**: it names the file instead,
since saving there would fork it from whoever you got it from. **d** puts it
back the way that file has it.
Editing changes the mode for every screen looking at the deck.

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
kit again after changing them).

## Esc and q

Every screen of the deck's own (the DECK tab, FLEET, the panels, NOTES, the
menus) takes these two the same way:

- **Esc** goes back one step: it drops a pick, a filter or a search, leaves
  a page for its list, gives the tab back to a zoomed pane. With nothing
  left to go back from, it closes a screen you opened from somewhere (a
  card, a key of the DECK tab, the `+` menu, a shell) and you're back
  there. A pane of your tab stays where it is: Esc never closes it.
- **q** closes what you're looking at: a page goes back to its list, a
  picker to the step before it, a panel ends. A pane of your tab then
  asks, like any program that ends (below): Enter opens it again.
- **?** lists the keys of the screen you're on, the ones its bar doesn't
  show too; q goes back to it.
- While you type (a filter, a search, a note), q is a letter and Esc
  cancels the typing.

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
phone kit adds KEYBOARD, EDIT, ZOOM and EXIT).

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
