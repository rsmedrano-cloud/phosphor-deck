"""phosphor tts - text to speech notifications with multiple voices (including GLaDOS).

Provides speech synthesis for notifications and messages with selectable voice profiles:
  - glados: GLaDOS from Portal (via https://github.com/nimaid/GLaDOS-TTS.git)
  - adjutant: StarCraft Adjutant military tactical AI (Piper / espeak)
  - hal: HAL 9000 calm computer voice (Piper / espeak)
  - spanish: Spanish neural voice (Piper davefx)
  - synth: Retro synthesized robotic voice (procedural)
  - system: Standard system voice (espeak, say, or spd-say)

Assists the user in installing optional neural models and engines:
  phosphor tts install glados      install GLaDOS neural voice engine
  phosphor tts install piper       install Piper local neural engine
  phosphor tts install models      install extra voice models (Adjutant, HAL, Spanish)
  phosphor tts install all         install everything
"""
import io, json, math, os, re, shutil, struct, subprocess, sys, tarfile, tempfile, threading, time, wave
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deckconf, dlog
from ui import OK, WARN, BAD, PH, AMB, DIM, RST

VOICES = {
    "glados": "GLaDOS (Portal AI, via nimaid/GLaDOS-TTS)",
    "adjutant": "StarCraft Adjutant (tactical AI)",
    "hal": "HAL 9000 (calm computer voice)",
    "spanish": "Spanish voice (Español, DaveFX)",
    "synth": "Retro synthesized voice (procedural)",
    "system": "System text-to-speech (espeak / say / spd-say)",
}

DEFAULT_GLADOS_DIR = os.path.expanduser("~/.local/share/phosphor/glados-tts")
DEFAULT_VOICES_DIR = os.path.expanduser("~/.local/share/phosphor/voices")
BIN_DIR = os.path.expanduser("~/.local/bin")
GLADOS_REPO_URL = "https://github.com/nimaid/GLaDOS-TTS.git"
GLADOS_MODEL_URLS = [
    ("https://github.com/dnhkng/GlaDOS/releases/download/0.1/glados.onnx", "glados/models/glados.onnx"),
    ("https://github.com/dnhkng/GlaDOS/releases/download/0.1/phomenizer_en.onnx", "glados/models/phomenizer_en.onnx"),
]

VOICE_MODELS = {
    "adjutant": {
        "name": "Adjutant (StarCraft AI assistant)",
        "file": "en_US-lessac-medium.onnx",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
    "hal": {
        "name": "HAL 9000 (calm computer voice)",
        "file": "en_US-ryan-medium.onnx",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/medium/en_US-ryan-medium.onnx.json",
    },
    "spanish": {
        "name": "Spanish / Español (DaveFX)",
        "file": "es_ES-davefx-medium.onnx",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx",
        "json_url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json",
    },
}


def get_config(prof=None):
    """Read [tts] settings from profile."""
    if prof is None:
        prof, _ = deckconf.load()
    t = (prof or {}).get("tts") or {}
    deck_sec = (prof or {}).get("deck") or {}
    enabled = t.get("enabled", deck_sec.get("tts", False))
    voice_name = t.get("voice", "glados")
    custom_path = t.get("glados_path", "")
    vol = float(t.get("volume", 1.0))
    alerts = bool(t.get("fleet_alerts", False))
    return {
        "enabled": enabled,
        "voice": voice_name,
        "glados_path": custom_path,
        "volume": vol,
        "fleet_alerts": alerts,
    }


def get_glados_dir(cfg=None):
    """Expanded path to GLaDOS-TTS directory."""
    if cfg and cfg.get("glados_path"):
        return os.path.expanduser(cfg["glados_path"])
    env_dir = os.environ.get("PHOSPHOR_GLADOS_PATH")
    if env_dir:
        return os.path.expanduser(env_dir)
    return DEFAULT_GLADOS_DIR


def get_voices_dir():
    """Directory where Piper neural voice models live."""
    return os.environ.get("PHOSPHOR_VOICES_PATH") or DEFAULT_VOICES_DIR


def is_glados_ready(target_dir=None):
    """Check if GLaDOS-TTS is installed and its models are downloaded."""
    d = target_dir or get_glados_dir()
    if not os.path.isdir(d):
        return False, "directory %s does not exist" % d
    speak_script = os.path.join(d, "speak.py")
    if not os.path.isfile(speak_script):
        return False, "speak.py not found in %s" % d
    m1 = os.path.join(d, "glados", "models", "glados.onnx")
    m2 = os.path.join(d, "glados", "models", "phomenizer_en.onnx")
    alt1 = os.path.join(d, "models", "glados.onnx")
    alt2 = os.path.join(d, "models", "phomenizer_en.onnx")
    if not (os.path.isfile(m1) or os.path.isfile(alt1)):
        return False, "glados.onnx model missing"
    if not (os.path.isfile(m2) or os.path.isfile(alt2)):
        return False, "phomenizer_en.onnx model missing"
    return True, "ready"


def find_audio_player():
    """Find an available command to play wav files."""
    for cmd_name in ["paplay", "pw-play", "aplay", "mpv", "ffplay", "play"]:
        bin_path = shutil.which(cmd_name)
        if bin_path:
            return cmd_name, bin_path
    return None, None


def find_system_tts():
    """Find installed system text-to-speech binaries."""
    for name in ["espeak-ng", "espeak", "say", "spd-say"]:
        p = shutil.which(name)
        if p:
            return name, p
    return None, None


def find_piper():
    """Find installed piper binary."""
    # Check ~/.local/bin/piper first, then PATH
    user_p = os.path.join(BIN_DIR, "piper")
    if os.path.isfile(user_p) and os.access(user_p, os.X_OK):
        return user_p
    return shutil.which("piper")


def has_models():
    """Check if any extra neural voice models are installed."""
    vdir = get_voices_dir()
    if not os.path.isdir(vdir):
        return False
    for vinfo in VOICE_MODELS.values():
        if os.path.isfile(os.path.join(vdir, vinfo["file"])):
            return True
    return False


def list_installed_models():
    """Return dict of model_key -> bool indicating which voice models are present."""
    vdir = get_voices_dir()
    res = {}
    for k, vinfo in VOICE_MODELS.items():
        p = os.path.join(vdir, vinfo["file"])
        res[k] = os.path.isfile(p)
    return res


def generate_synth_wav(text, output_wav, style="synth"):
    """Generate a lightweight procedural wav for robotic speech fallback."""
    sample_rate = 22050
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        words = ["beep"]

    pitch_base = 220 if style == "glados" else (130 if style == "adjutant" else (95 if style == "hal" else 180))
    frames = bytearray()

    for w_idx, word in enumerate(words[:15]):
        dur = max(0.08, min(0.28, len(word) * 0.04))
        total_samples = int(sample_rate * dur)
        w_pitch = pitch_base * (1.0 + (w_idx % 4) * 0.08 - (w_idx % 3) * 0.04)

        for s_idx in range(total_samples):
            t_sec = float(s_idx) / sample_rate
            carrier = math.sin(2.0 * math.pi * w_pitch * t_sec)
            modulator = 0.5 * math.sin(2.0 * math.pi * (w_pitch * 2.0) * t_sec)
            val = (carrier + modulator) * 0.5

            if style == "synth":
                val = 0.8 if val > 0 else -0.8
            elif style == "adjutant":
                val = val * 0.7 + ((s_idx % 17) / 17.0 - 0.5) * 0.3

            env = 1.0
            attack = int(sample_rate * 0.01)
            decay = int(sample_rate * 0.02)
            if s_idx < attack:
                env = float(s_idx) / max(1, attack)
            elif s_idx > total_samples - decay:
                env = float(total_samples - s_idx) / max(1, decay)

            sample_int = int(32767 * 0.35 * val * env)
            sample_int = max(-32768, min(32767, sample_int))
            frames += struct.pack("<h", sample_int)

        pause_samples = int(sample_rate * 0.04)
        frames += b"\x00\x00" * pause_samples

    with wave.open(output_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(frames)


def play_wav(wav_path):
    """Play a WAV audio file using available system player or ALSA."""
    player_name, player_bin = find_audio_player()
    if player_name == "paplay":
        subprocess.run([player_bin, wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return True
    if player_name == "pw-play":
        subprocess.run([player_bin, wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return True
    if player_name == "aplay":
        subprocess.run([player_bin, "-q", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return True
    if player_name == "mpv":
        subprocess.run([player_bin, "--no-terminal", "--really-quiet", wav_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return True
    if player_name == "ffplay":
        subprocess.run([player_bin, "-nodisp", "-autoexit", "-loglevel", "quiet", wav_path],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return True
    if player_name == "play":
        subprocess.run([player_bin, "-q", wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        return True

    dlog.event_throttled("TTS", "no-audio-player")
    return False


def speak_piper(text, model_file):
    """Synthesize and play speech using Piper neural engine."""
    piper_bin = find_piper()
    if not piper_bin:
        return False
    if not os.path.isfile(model_file):
        return False
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_out = tf.name
        proc = subprocess.run([piper_bin, "--model", model_file, "--output_file", wav_out],
                              input=text, text=True, capture_output=True, timeout=25)
        if proc.returncode == 0 and os.path.exists(wav_out) and os.path.getsize(wav_out) > 44:
            play_wav(wav_out)
            return True
    except Exception as e:
        dlog.event("TTS", "piper-speak-failed", str(e)[:60])
    finally:
        if "wav_out" in locals() and os.path.exists(wav_out):
            try: os.remove(wav_out)
            except OSError: pass
    return False


def speak(text, voice=None, cfg=None, async_mode=False):
    """Speak the given text with the specified voice."""
    if async_mode:
        t = threading.Thread(target=speak, args=(text, voice, cfg, False), daemon=True)
        t.start()
        return

    if cfg is None:
        cfg = get_config()
    v_target = voice or cfg.get("voice", "glados")

    clean_txt = re.sub(r"\x1b\[[0-9;]*[mK]", "", text).strip()
    if not clean_txt:
        return

    # Check for Piper neural models first for adjutant, hal, spanish
    vdir = get_voices_dir()
    if v_target in VOICE_MODELS:
        m_path = os.path.join(vdir, VOICE_MODELS[v_target]["file"])
        if os.path.isfile(m_path) and find_piper():
            if speak_piper(clean_txt, m_path):
                return

    # 1. GLaDOS voice
    if v_target == "glados":
        g_dir = get_glados_dir(cfg)
        ready_flag, reason = is_glados_ready(g_dir)
        if ready_flag:
            py_bin = os.path.join(g_dir, ".venv", "bin", "python")
            if not os.path.isfile(py_bin):
                py_bin = os.path.join(g_dir, "venv", "bin", "python")
            if not os.path.isfile(py_bin):
                py_bin = sys.executable

            speak_script = os.path.join(g_dir, "speak.py")
            try:
                subprocess.run([py_bin, speak_script, "-t", clean_txt],
                               cwd=g_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
                return
            except Exception as e:
                dlog.event("TTS", "glados-run-failed", str(e)[:60])
        else:
            dlog.event("TTS", "glados-not-ready", reason[:60])
            v_target = "synth"

    # 2. System TTS (espeak / say / spd-say)
    sys_tts_name, sys_tts_bin = find_system_tts()

    if sys_tts_name in ("espeak-ng", "espeak"):
        if v_target == "adjutant":
            args = [sys_tts_bin, "-v", "en+whisper", "-p", "60", "-s", "135", clean_txt]
        elif v_target == "hal":
            args = [sys_tts_bin, "-v", "en-us", "-p", "22", "-s", "120", clean_txt]
        elif v_target == "spanish":
            args = [sys_tts_bin, "-v", "es", "-s", "145", clean_txt]
        elif v_target == "synth":
            args = [sys_tts_bin, "-v", "en+klatt", "-p", "80", "-s", "145", clean_txt]
        else:
            args = [sys_tts_bin, "-s", "150", clean_txt]
        try:
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            return
        except Exception:
            pass

    if sys_tts_name == "say":
        voice_opt = ["-v", "Victoria"] if v_target == "adjutant" else (["-v", "Fred"] if v_target == "hal" else [])
        if v_target == "spanish":
            voice_opt = ["-v", "Monica"]
        try:
            subprocess.run([sys_tts_bin] + voice_opt + [clean_txt],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            return
        except Exception:
            pass

    if sys_tts_name == "spd-say":
        try:
            subprocess.run([sys_tts_bin, "-t", "female1", clean_txt],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            return
        except Exception:
            pass

    # Pure procedural synthesis fallback
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            wav_name = tf.name
        generate_synth_wav(clean_txt, wav_name, style=v_target)
        play_wav(wav_name)
    except Exception as e:
        dlog.event("TTS", "synth-failed", str(e)[:60])
    finally:
        if "wav_name" in locals() and os.path.exists(wav_name):
            try:
                os.remove(wav_name)
            except OSError:
                pass


def speak_async(text, voice=None, cfg=None):
    """Non-blocking call to speak."""
    return speak(text, voice=voice, cfg=cfg, async_mode=True)


def notify_hook(text, tab="", voice=None, force=False, fleet=False):
    """Hook invoked on notifications to speak if enabled. A fleet health
    alert (a machine going down or coming back) only speaks when [tts]
    fleet_alerts is also on: most people want to hear a message meant for
    them, not every blip of a machine they're not looking at."""
    cfg = get_config()
    if fleet and not cfg.get("fleet_alerts"):
        return
    if not (force or cfg.get("enabled")):
        return
    v_voice = voice or cfg.get("voice", "glados")
    clean = text.strip()
    if len(clean) > 160:
        clean = clean[:157] + "..."
    speak_async(clean, voice=v_voice, cfg=cfg)


def download_file_with_progress(url, dest_path):
    """Download a file with visual progress indication."""
    import urllib.request
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_dest = dest_path + ".tmp"
    print("  fetching %s -> %s" % (url.split("/")[-1], os.path.relpath(dest_path, os.path.expanduser("~"))))
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "phosphor-deck"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_dest, "wb") as out_f:
            length_hdr = resp.headers.get("Content-Length")
            total = int(length_hdr) if length_hdr else None
            downloaded = 0
            chunk_size = 64 * 1024
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    mb = downloaded / (1024 * 1024)
                    tot_mb = total / (1024 * 1024)
                    sys.stdout.write("\r    %d%% (%.1f / %.1f MB)" % (pct, mb, tot_mb))
                else:
                    mb = downloaded / (1024 * 1024)
                    sys.stdout.write("\r    %.1f MB" % mb)
                sys.stdout.flush()
        print()
        os.replace(tmp_dest, dest_path)
        return True
    except Exception as e:
        print("\n  download failed: %s" % e)
        if os.path.exists(tmp_dest):
            try: os.remove(tmp_dest)
            except OSError: pass
        return False


def install_piper():
    """Install Piper neural TTS engine binary from GitHub releases into ~/.local/bin."""
    import urllib.request
    print("\n[Piper] Installing Piper local neural TTS engine...")
    api_url = "https://api.github.com/repos/rhasspy/piper/releases/latest"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "phosphor-deck"})
        with urllib.request.urlopen(req, timeout=20) as r:
            rel = json.load(r)
        asset_url = None
        for a in rel.get("assets", []):
            if "linux_x86_64" in a["name"]:
                asset_url = a["browser_download_url"]
                break
        if not asset_url:
            print("%s could not find x86_64 release for Piper." % BAD)
            return 1
        with tempfile.TemporaryDirectory() as td:
            tar_path = os.path.join(td, "piper.tar.gz")
            if not download_file_with_progress(asset_url, tar_path):
                return 1
            print("  extracting Piper binary...")
            extract_dir = os.path.join(td, "extracted")
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(tar_path) as tf:
                tf.extractall(extract_dir)

            piper_src = None
            for root, _, files in os.walk(extract_dir):
                if "piper" in files:
                    fp = os.path.join(root, "piper")
                    if os.path.isfile(fp) and not os.path.islink(fp):
                        piper_src = fp
                        break
            if not piper_src:
                print("%s piper binary not found in package." % BAD)
                return 1

            # Copy piper and its shared libraries to ~/.local/lib/piper or ~/.local/bin
            piper_dir = os.path.dirname(piper_src)
            target_bin = os.path.join(BIN_DIR, "piper")
            target_lib = os.path.expanduser("~/.local/lib/piper")
            os.makedirs(target_lib, exist_ok=True)
            for item in os.listdir(piper_dir):
                s = os.path.join(piper_dir, item)
                d = os.path.join(target_lib, item)
                if os.path.isdir(s):
                    if os.path.exists(d): shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)

            # Wrapper script in ~/.local/bin/piper
            wrapper = ("#!/bin/sh\n"
                       "DIR=\"%s\"\n"
                       "export LD_LIBRARY_PATH=\"$DIR:$LD_LIBRARY_PATH\"\n"
                       "exec \"$DIR/piper\" \"$@\"\n" % target_lib)
            open(target_bin, "w").write(wrapper)
            os.chmod(target_bin, 0o755)
            print("%s Piper installed in %s" % (OK, target_bin))
            return 0
    except Exception as e:
        print("%s Piper installation failed: %s" % (BAD, e))
        return 1


def install_models(which="all"):
    """Install optional voice models (Adjutant, HAL 9000, Spanish)."""
    vdir = get_voices_dir()
    os.makedirs(vdir, exist_ok=True)
    targets = VOICE_MODELS.keys() if which in ("all", "models") else [which]
    success_count = 0
    for t_name in targets:
        if t_name not in VOICE_MODELS:
            print("  unknown voice model: %s" % t_name)
            continue
        vinfo = VOICE_MODELS[t_name]
        print("\n[Model] %s (%s)..." % (vinfo["name"], t_name))
        dest_onnx = os.path.join(vdir, vinfo["file"])
        dest_json = dest_onnx + ".json"
        ok_onnx = download_file_with_progress(vinfo["url"], dest_onnx)
        ok_json = download_file_with_progress(vinfo["json_url"], dest_json)
        if ok_onnx and ok_json:
            print("  %s %s ready" % (OK, t_name))
            success_count += 1
        else:
            print("  %s failed downloading %s" % (BAD, t_name))
    return 0 if success_count > 0 else 1


def remove_models():
    """Remove installed extra voice models."""
    vdir = get_voices_dir()
    if os.path.isdir(vdir):
        shutil.rmtree(vdir)
        return True
    return False


def remove_glados():
    """Remove GLaDOS-TTS installation."""
    gdir = get_glados_dir()
    if os.path.isdir(gdir):
        shutil.rmtree(gdir)
        return True
    return False


def install_glados(target_dir=None):
    """Guided installation assistant for GLaDOS-TTS (nimaid/GLaDOS-TTS)."""
    dest = target_dir or get_glados_dir()
    print("\n%s╔══════════════════════════════════════════════════════════════════╗%s" % (PH, RST))
    print("%s║   GLaDOS Text-To-Speech Installer Assistant                      ║%s" % (PH, RST))
    print("%s╚══════════════════════════════════════════════════════════════════╝%s\n" % (PH, RST))
    print("This will set up the GLaDOS neural voice engine:")
    print("  · Repository: %s" % GLADOS_REPO_URL)
    print("  · Target:     %s" % dest)
    print("  · Engine:     VITS / Piper ONNX models for Portal's GLaDOS\n")

    if not shutil.which("git"):
        print("%s git is not installed. Please install git first (`sudo apt install git`)." % BAD)
        return 1

    if not os.path.isdir(dest):
        print("[1/4] Cloning GLaDOS-TTS repository...")
        res = subprocess.run(["git", "clone", GLADOS_REPO_URL, dest])
        if res.returncode != 0:
            print("%s git clone failed." % BAD)
            return 1
    else:
        print("[1/4] Updating existing GLaDOS-TTS repository...")
        subprocess.run(["git", "-C", dest, "pull"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    print("\n[2/4] Setting up Python virtual environment...")
    venv_dir = os.path.join(dest, ".venv")
    py_venv = os.path.join(venv_dir, "bin", "python")
    pip_venv = os.path.join(venv_dir, "bin", "pip")

    if not os.path.isfile(py_venv):
        res = subprocess.run([sys.executable, "-m", "venv", venv_dir])
        if res.returncode != 0:
            print("%s failed to create virtualenv at %s" % (WARN, venv_dir))
            print("  If python3-venv is missing: sudo apt install python3-venv")
            py_venv = sys.executable
            pip_venv = None

    if pip_venv and os.path.isfile(pip_venv):
        print("  installing dependencies (onnxruntime, sounddevice, num2words)...")
        req_file = os.path.join(dest, "requirements.txt")
        if os.path.isfile(req_file):
            subprocess.run([pip_venv, "install", "--upgrade", "pip"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            sub_res = subprocess.run([pip_venv, "install", "-r", req_file])
            if sub_res.returncode != 0:
                print("%s pip install returned non-zero. Attempting core packages directly..." % WARN)
                subprocess.run([pip_venv, "install", "onnxruntime", "sounddevice", "num2words", "numpy"])

    print("\n[3/4] Checking and downloading GLaDOS neural voice models...")
    for url, rel_dest in GLADOS_MODEL_URLS:
        full_dest = os.path.join(dest, rel_dest)
        if not os.path.isfile(full_dest):
            ok_dl = download_file_with_progress(url, full_dest)
            if not ok_dl:
                print("%s failed to download %s" % (BAD, url))
                print("  You can manually run %s/download_models_linux.bash" % dest)
                return 1
        else:
            print("  %s %s" % (OK, rel_dest))

    print("\n[4/4] Verifying GLaDOS TTS synthesis...")
    speak_script = os.path.join(dest, "speak.py")
    test_phrase = "GLaDOS text to speech system online."
    try:
        t_res = subprocess.run([py_venv, speak_script, "-t", test_phrase],
                               cwd=dest, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
        if t_res.returncode == 0:
            print("  %s Test speech executed successfully." % OK)
        else:
            print("  %s Test returned code %d (audio hardware may be muted or offline)." % (WARN, t_res.returncode))
    except Exception as e:
        print("  %s Test run note: %s" % (WARN, e))

    print("\n%s GLaDOS-TTS is configured and ready! %s\n" % (PH, RST))
    print("To enable it for notifications, add to ~/.config/phosphor/deck.toml:")
    print("  [tts]")
    print('  enabled = true')
    print('  voice   = "glados"\n')
    print("Or run:")
    print("  phosphor tts on\n")
    return 0


def status():
    """Print detailed status of TTS engines and voices."""
    cfg = get_config()
    print("Text-to-Speech (TTS) Status:")
    print("  enabled:        %s" % (OK + " on" if cfg["enabled"] else DIM + "off" + RST))
    print("  active voice:   %s (%s)" % (PH + cfg["voice"] + RST, VOICES.get(cfg["voice"], "custom")))
    print("  fleet alerts:   %s" % ("yes" if cfg["fleet_alerts"] else "no"))

    g_dir = get_glados_dir(cfg)
    g_ok, g_detail = is_glados_ready(g_dir)
    print("\nGLaDOS Voice Model:")
    print("  location:       %s" % g_dir)
    print("  status:         %s (%s)" % (OK + " ready" if g_ok else WARN + " not ready", g_detail))
    if not g_ok:
        print("  install with:   phosphor tts install glados")

    piper_bin = find_piper()
    print("\nPiper Neural Engine:")
    print("  binary:         %s" % ("%s (%s)" % (OK, piper_bin) if piper_bin else DIM + "not installed (install with: phosphor tts install piper)" + RST))

    models_installed = list_installed_models()
    print("\nNeural Voice Models (Piper):")
    vdir = get_voices_dir()
    for m_key, m_info in VOICE_MODELS.items():
        have_m = models_installed.get(m_key, False)
        print("  · %-10s %-32s %s" % (m_key, m_info["name"], OK + " installed" if have_m else DIM + "not installed" + RST))
    if not any(models_installed.values()):
        print("  install with:   phosphor tts install models")

    sys_name, sys_path = find_system_tts()
    print("\nSystem Backends:")
    print("  system speech:  %s" % ("%s (%s)" % (OK, sys_path) if sys_path else DIM + "none (procedural fallback active)" + RST))

    p_name, p_path = find_audio_player()
    print("  audio player:   %s" % ("%s (%s)" % (OK, p_name) if p_name else WARN + "no player found (aplay/paplay/pw-play)" + RST))

    print("\nAvailable Voices:")
    for v_k, v_desc in VOICES.items():
        cur = " (active)" if v_k == cfg["voice"] else ""
        print("  · %-10s %s%s" % (v_k, v_desc, PH + cur + RST if cur else ""))
    print()
    return 0


def set_enabled(enable=True):
    """Enable or disable TTS in profile."""
    prof, prof_path = deckconf.load()
    if deckconf.example():
        print("No profile yet: phosphor init writes yours.")
        return 1
    text = open(prof_path).read()
    if "[tts]" in text:
        if re.search(r"\[tts\][^\[]*\benabled\s*=\s*\w+", text):
            text = re.sub(r"(\[tts\][^\[]*\benabled\s*=\s*)\w+", r"\g<1>%s" % ("true" if enable else "false"), text)
        else:
            text = text.replace("[tts]", "[tts]\nenabled = %s" % ("true" if enable else "false"))
    else:
        text += "\n[tts]\nenabled = %s\nvoice = \"glados\"\n" % ("true" if enable else "false")
    open(prof_path, "w").write(text)
    print("TTS %s in %s" % ("enabled" if enable else "disabled", prof_path))
    return 0


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: phosphor tts [\"message to speak\"]")
        print("       phosphor tts --voice VOICE \"message\"")
        print("       phosphor tts --list")
        print("       phosphor tts status")
        print("       phosphor tts install [glados | piper | models | all]")
        print("       phosphor tts on | off")
        return 0

    if argv[0] == "status":
        return status()

    if argv[0] in ("--list", "--voices", "voices"):
        print("Available voices:")
        for k, desc in VOICES.items():
            print("  %-10s %s" % (k, desc))
        return 0

    if argv[0] == "install":
        target = argv[1] if len(argv) > 1 else "glados"
        if target in ("glados", "GLaDOS", "glados-tts"):
            return install_glados()
        if target == "piper":
            return install_piper()
        if target in ("models", "all") or target in VOICE_MODELS:
            rc = 0
            if target == "all":
                install_piper()
                install_glados()
            rc = install_models(which=target)
            return rc
        print("unknown install target: %s (available: glados, piper, models, all)" % target)
        return 1

    if argv[0] == "on":
        return set_enabled(True)
    if argv[0] == "off":
        return set_enabled(False)

    voice_sel = None
    if "--voice" in argv:
        idx = argv.index("--voice")
        if idx + 1 < len(argv):
            voice_sel = argv[idx + 1]
            del argv[idx:idx + 2]
        else:
            print("error: --voice requires a voice name")
            return 1

    msg = " ".join(argv).strip()
    if not msg:
        print("error: nothing to speak")
        return 1

    speak(msg, voice=voice_sel, async_mode=False)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
