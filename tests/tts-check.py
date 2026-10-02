#!/usr/bin/env python3
"""Text-to-Speech notifications and GLaDOS voice model checks.

    python3 tests/tts-check.py

Verifies:
- tts configuration reading and voice options
- GLaDOS voice model readiness check
- Procedural audio synthesis (WAV generation and validity)
- notify hook execution
- CLI commands (--list, status)
"""
import os, sys, tempfile, wave
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import tts

fails = []
def check(what, ok):
    if not ok:
        fails.append(what)

# 1. Config and voices
cfg = tts.get_config({})
check("default enabled is False", cfg["enabled"] is False)
check("default voice is glados", cfg["voice"] == "glados")
check("glados voice is registered", "glados" in tts.VOICES)
check("adjutant voice is registered", "adjutant" in tts.VOICES)
check("hal voice is registered", "hal" in tts.VOICES)
check("spanish voice is registered", "spanish" in tts.VOICES)
check("adjutant model is registered in VOICE_MODELS", "adjutant" in tts.VOICE_MODELS)
check("hal model is registered in VOICE_MODELS", "hal" in tts.VOICE_MODELS)
check("spanish model is registered in VOICE_MODELS", "spanish" in tts.VOICE_MODELS)

# 2. GLaDOS readiness check on empty directory
with tempfile.TemporaryDirectory() as td:
    ready, reason = tts.is_glados_ready(td)
    check("empty dir is not ready", ready is False)
    check("reason mentions speak.py", "speak.py" in reason)

    # create fake speak.py and models
    os.makedirs(os.path.join(td, "glados", "models"), exist_ok=True)
    open(os.path.join(td, "speak.py"), "w").write("# fake speak\n")
    open(os.path.join(td, "glados", "models", "glados.onnx"), "w").write("fake onnx\n")
    ready, reason = tts.is_glados_ready(td)
    check("missing second model reports not ready", ready is False)
    open(os.path.join(td, "glados", "models", "phomenizer_en.onnx"), "w").write("fake onnx\n")
    ready, reason = tts.is_glados_ready(td)
    check("with all files it is ready", ready is True)

# 3. Procedural WAV synthesis
with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
    wav_path = tf.name

try:
    tts.generate_synth_wav("Host unreachable 100% disk", wav_path, style="synth")
    check("wav file created", os.path.isfile(wav_path) and os.path.getsize(wav_path) > 100)
    with wave.open(wav_path, "rb") as wf:
        check("1 channel", wf.getnchannels() == 1)
        check("16-bit", wf.getsampwidth() == 2)
        check("22050 rate", wf.getframerate() == 22050)
        check("frames present", wf.getnframes() > 0)
finally:
    if os.path.exists(wav_path):
        os.remove(wav_path)

# 4. Notify hook execution (with forced=True and False)
tts.notify_hook("Unit test notification", tab="SYS", force=False)  # should not throw
tts.notify_hook("Unit test notification", tab="SYS", voice="synth", force=True)  # should not throw

# 4b. fleet=True gates on [tts] fleet_alerts too, on top of enabled -- a
# manual/mention notify (fleet=False) is unaffected either way.
spoke = []
real_speak_async = tts.speak_async
tts.speak_async = lambda text, voice=None, cfg=None: spoke.append(text)
try:
    import deckconf
    real_load = deckconf.load
    def enabled_no_fleet():
        return {"tts": {"enabled": True, "fleet_alerts": False}}, "test"
    deckconf.load = lambda: enabled_no_fleet()
    spoke.clear()
    tts.notify_hook("db-box is unreachable", tab="FLEET", fleet=True)
    check("fleet alert silent: enabled but fleet_alerts off", spoke == [])
    tts.notify_hook("someone mentioned you", tab="COMMS", fleet=False)
    check("a normal notify still speaks with enabled alone", spoke == ["someone mentioned you"])

    def enabled_with_fleet():
        return {"tts": {"enabled": True, "fleet_alerts": True}}, "test"
    deckconf.load = lambda: enabled_with_fleet()
    spoke.clear()
    tts.notify_hook("db-box is back", tab="FLEET", fleet=True)
    check("fleet alert speaks once fleet_alerts is also on", spoke == ["db-box is back"])
finally:
    deckconf.load = real_load
    tts.speak_async = real_speak_async

# 4c. render(): the voice into a file, for the clip a push carries
import time
with tempfile.TemporaryDirectory() as td:
    # a GLaDOS that writes its -o file and records how it was called
    os.makedirs(os.path.join(td, "glados", "models"))
    for m in ("glados.onnx", "phomenizer_en.onnx"):
        open(os.path.join(td, "glados", "models", m), "w").write("x")
    open(os.path.join(td, "speak.py"), "w").write(
        "import sys, shutil\n"
        "open(%r, 'w').write(' '.join(sys.argv[1:]))\n"
        "a = sys.argv; shutil.copy(%r, a[a.index('-o') + 1])\n"
        % (os.path.join(td, "argv"), os.path.join(td, "src.wav")))
    tts.generate_synth_wav("hello", os.path.join(td, "src.wav"))
    g = {"glados_path": td, "voice": "glados"}
    out = tts.render("db-box is down", cfg=g)
    called = open(os.path.join(td, "argv")).read() if os.path.exists(os.path.join(td, "argv")) else ""
    check("glados renders into a file", out and os.path.getsize(out) > 44)
    check("glados: quiet, never the speaker", "-q" in called.split())
    check("glados: the text", "db-box is down" in called)
    if out: os.remove(out)

    real_sys, real_player = tts.find_system_tts, tts.find_audio_player
    tts.find_system_tts = lambda: (None, None)
    try:
        g = {"glados_path": os.path.join(td, "none"), "voice": "glados"}
        out = tts.render("db-box is down", cfg=g)
        check("glados missing: the synth fallback still renders", out and wave.open(out).getnframes() > 0)
        if out: os.remove(out)
        tts.find_system_tts = lambda: ("spd-say", "/bin/false")
        before = set(os.listdir(tempfile.gettempdir()))
        check("spd-say can't write a file: no clip", tts.render("x", cfg=g) == "")
        check("no clip leaves no file", not [f for f in set(os.listdir(tempfile.gettempdir())) - before
                                             if f.startswith("phosphor-tts-")])
        check("empty text: no clip", tts.render("  ", cfg=g) == "")

        # clip() follows the same gating as speaking
        real_load = deckconf.load
        try:
            deckconf.load = lambda: ({"tts": {"enabled": False}}, "t")
            check("tts off: no clip", tts.clip("x") == "")
            deckconf.load = lambda: ({"tts": {"enabled": True, "glados_path": g["glados_path"]}}, "t")
            check("fleet alert without fleet_alerts: no clip", tts.clip("x", fleet=True) == "")
            tts.find_system_tts = lambda: (None, None)
            c = tts.clip("x" * 400)
            check("tts on: a clip", bool(c))

            # notify_hook plays that same file, then removes it
            tts.find_audio_player = lambda: ("paplay", "/bin/true")
            spoke.clear()
            tts.speak_async = lambda text, voice=None, cfg=None: spoke.append(text)
            tts.notify_hook("x", wav=c)
            for _ in range(50):
                if not os.path.exists(c): break
                time.sleep(0.1)
            check("the clip is played, not synthesized again", spoke == [])
            check("the clip is removed once played", not os.path.exists(c))
            c = tts.clip("y")
            tts.find_audio_player = lambda: (None, None)
            tts.notify_hook("y", wav=c)
            check("no player: removed, spoken the old way", not os.path.exists(c) and spoke == ["y"])
            c = tts.clip("z")
            deckconf.load = lambda: ({"tts": {"enabled": False}}, "t")
            tts.notify_hook("z", wav=c)
            check("not spoken: the clip still goes", not os.path.exists(c) and spoke == ["y"])
        finally:
            deckconf.load = real_load
            tts.speak_async = real_speak_async
    finally:
        tts.find_system_tts, tts.find_audio_player = real_sys, real_player

# 5. CLI interface
saved_argv = sys.argv
try:
    sys.argv = ["phosphor-tts", "status"]
    rc = tts.main()
    check("status returns 0", rc == 0)

    sys.argv = ["phosphor-tts", "--list"]
    rc = tts.main()
    check("--list returns 0", rc == 0)

    sys.argv = ["phosphor-tts", "--voice", "synth", "test"]
    rc = tts.main()
    check("speak returns 0", rc == 0)
finally:
    sys.argv = saved_argv

if fails:
    print("FAILED:\n  " + "\n  ".join(fails))
    sys.exit(1)
print("ok")
