"""phosphor notify: a line in the events feed, a mark on the tab it came
from, and (each when it's on) a push, a voice and a floating toast."""
import os, sys
import deckconf, proc

def load_profile():
    prof, p = deckconf.load()
    if prof is None:
        print("can't read the profile (%s): %s" % (p, deckconf.ERR))
    return prof, p

def main(argv=None):
    import subprocess as _sp
    argv = list(sys.argv[1:] if argv is None else argv)
    tab = ""
    voice_opt = None
    tts_opt = None
    push_opt = None
    # Internal, for fleet and mentions (which already write their own
    # event line, and mark a fleet health blip so TTS can gate it
    # separately) -- not in the usage string, same as mentions --prepare.
    no_event = "--no-event" in argv
    if no_event: argv.remove("--no-event")
    fleet_alert = "--fleet-alert" in argv
    if fleet_alert: argv.remove("--fleet-alert")
    if "--push" in argv:
        push_opt = True
        argv.remove("--push")
    elif "--no-push" in argv:
        push_opt = False
        argv.remove("--no-push")
    if "--voice" in argv:
        i = argv.index("--voice")
        voice_opt = argv[i + 1] if i + 1 < len(argv) else None
        del argv[i:i + 2]
    if "--tts" in argv:
        tts_opt = True
        argv.remove("--tts")
    elif "--no-tts" in argv:
        tts_opt = False
        argv.remove("--no-tts")
    if "--tab" in argv:
        i = argv.index("--tab")
        tab = argv[i + 1] if i + 1 < len(argv) else ""
        del argv[i:i + 2]
    txt = " ".join(argv).strip()
    if not txt:
        print("usage: phosphor notify [--tab TAB] [--voice VOICE] [--tts|--no-tts] [--push|--no-push] \"message\""); return 1
    d = deckconf.cache_dir()   # PHOSPHOR_CACHE-aware: phosphor demo isolates this
    os.makedirs(d, exist_ok=True)
    if not no_event:
        with open(os.path.join(d, "events"), "a") as f:
            f.write("%s\t%s\n" % (tab, txt))
    # Spoken and pushed both: render the voice once, so the phone gets
    # the clip the brain plays (tts.notify_hook removes it after).
    wav = ""
    if push_opt is not False and tts_opt is not False:
        try:
            import push, tts
            if push.wants_clip(force=bool(push_opt)):
                wav = tts.clip(txt, voice=voice_opt, force=bool(tts_opt or voice_opt), fleet=fleet_alert)
        except Exception:
            wav = ""
    if push_opt is not False:
        try:
            import push
            ok, why = push.notify_hook(txt, tab=tab, force=bool(push_opt), attach=wav)
            if push_opt and not ok:
                print("push failed: %s" % why, file=sys.stderr)
        except Exception as e:
            if push_opt:
                print("push failed: %s" % e, file=sys.stderr)
    if tts_opt is not False:
        try:
            import tts
            tts.notify_hook(txt, tab=tab, voice=voice_opt, force=bool(tts_opt or voice_opt),
                            fleet=fleet_alert, wav=wav)
        except Exception:
            pass
    zj = proc.zellij()
    prof, _ = load_profile()
    sess = ((prof or {}).get("deck") or {}).get("session", "deck")
    flot = ((prof or {}).get("deck") or {}).get("notifier", False)
    # No floating panes needed for this part: a "<TAB> ●N" on the tab
    # it came from (or SYS with no --tab), same mechanism mentions.py
    # already uses for COMMS -- see tabmark.py. Runs whether or not
    # notifier is on: with notifier=false (the default), it's the only
    # on-screen trace a notification leaves.
    if zj:
        try:
            import tabmark
            tabmark.bump(sess, tab)
        except Exception:
            pass
    # Floating panes only with notifier = true: showing/hiding them is
    # the path that wedged zellij 0.45.
    if zj and flot:
        # The active tab, by id: `show-floating-panes` with no -t asks
        # zellij to resolve "the active tab" for this one-shot CLI call,
        # and that resolution isn't reliable (it can answer "Tab not
        # found" even though a tab plainly is active) -- an explicit -t
        # is the only way this has been seen to work every time.
        try:
            lt = _sp.run([zj, "-s", sess, "action", "list-tabs", "--state"],
                         capture_output=True, text=True, timeout=10).stdout
            active_id = next((ln.split()[0] for ln in lt.splitlines()[1:]
                              if len(ln.split()) > 3 and ln.split()[3] == "true"), None)
        except (OSError, _sp.SubprocessError):
            active_id = None
        show = [zj, "-s", sess, "action", "show-floating-panes"] + (["-t", active_id] if active_id else [])
        _sp.run(show, capture_output=True, timeout=10)
        # Remember exactly which tab this showed on -- almost always the
        # one the hider below will need to hide again. Looping
        # hide-floating-panes -t over every tab (shown or not) used to be
        # the only clue behind zellij 0.45's screen-thread freeze (see
        # DECK_UP in gen.py): touching tabs nothing was ever shown on was
        # pure risk for no reason, so the hider now only touches tabs
        # this file actually names.
        shown = os.path.join(d, "notify-shown-tabs")
        if active_id is not None:
            with open(shown, "a") as f:
                f.write(active_id + "\n")
        # A toast: it hides itself after a few seconds, unless a newer
        # event arrived meanwhile (the events file's mtime moved) -- only
        # the hider spawned by the latest notify actually runs.
        import shlex as _q
        ev = os.path.join(d, "events")
        secs = int(((prof or {}).get("deck") or {}).get("notify_seconds", 8))
        stamp = int(os.path.getmtime(ev))
        Z, S, SH = _q.quote(zj), _q.quote(sess), _q.quote(shown)
        hider = ("sleep %d; [ \"$(stat -c %%Y %s)\" = \"%d\" ] || exit 0; "
                 "if [ -f %s ]; then for id in $(sort -u %s); do "
                 "%s -s %s action hide-floating-panes -t \"$id\"; done; rm -f %s; "
                 "else %s -s %s action hide-floating-panes; fi"
                 % (secs, _q.quote(ev), stamp, SH, SH, Z, S, SH, Z, S))
        _sp.Popen(["/bin/sh", "-c", hider], start_new_session=True,
                  stdin=_sp.DEVNULL, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    return 0
