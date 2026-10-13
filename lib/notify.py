"""phosphor notify: a line in the events feed, a mark on the tab it came
from, and (each when it's on) a push and a voice."""
import os, sys
import deckconf, proc

def load_profile():
    prof, p = deckconf.load()
    if prof is None:
        print("can't read the profile (%s): %s" % (p, deckconf.ERR))
    return prof, p

def main(argv=None):
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
    # A "<TAB> ●N" on the tab
    # it came from (or SYS with no --tab), same mechanism mentions.py
    # already uses for COMMS -- see tabmark.py. It's the only on-screen
    # trace a notification leaves.
    if zj:
        try:
            import tabmark
            tabmark.bump(sess, tab)
        except Exception:
            pass
    return 0
