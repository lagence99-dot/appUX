"""Oreilles (micro + reconnaissance vocale locale Vosk) et voix (synthèse pyttsx3) de Celia.

La reconnaissance du prénom tourne entièrement sur votre ordinateur : rien n'est
envoyé sur Internet tant que vous n'avez pas appelé Celia.
"""
import difflib
import json
import queue
import re
import shutil
import sys
import threading
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

from .config import app_dir

VOSK_MODEL_NAME = "vosk-model-small-fr-0.22"
VOSK_MODEL_URL = f"https://alphacephei.com/vosk/models/{VOSK_MODEL_NAME}.zip"
SAMPLE_RATE = 16000


# --------------------------------------------------------------------------- #
#  Modèle de reconnaissance vocale
# --------------------------------------------------------------------------- #
def default_model_dir() -> Path:
    return app_dir() / "models" / VOSK_MODEL_NAME


def ensure_vosk_model(custom_path: str = "", progress=lambda msg: None) -> Path:
    """Retourne le dossier du modèle Vosk, en le téléchargeant (≈ 40 Mo) si besoin."""
    if custom_path:
        p = Path(custom_path)
        if not p.is_dir():
            raise FileNotFoundError(f"Modèle Vosk introuvable : {p}")
        return p
    target = default_model_dir()
    if (target / "am").is_dir() or (target / "conf").is_dir():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    zip_path = target.parent / f"{VOSK_MODEL_NAME}.zip"
    progress("Téléchargement du modèle vocal français (≈ 40 Mo)…")

    def hook(blocks, block_size, total):
        if total > 0:
            pct = min(100, blocks * block_size * 100 // total)
            progress(f"Téléchargement du modèle vocal… {pct} %")

    urllib.request.urlretrieve(VOSK_MODEL_URL, zip_path, hook)
    progress("Installation du modèle vocal…")
    tmp = target.parent / "_extract"
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    inner = next(tmp.iterdir())
    shutil.rmtree(target, ignore_errors=True)
    inner.rename(target)
    shutil.rmtree(tmp, ignore_errors=True)
    zip_path.unlink(missing_ok=True)
    return target


# --------------------------------------------------------------------------- #
#  Détection du prénom (mot de réveil)
# --------------------------------------------------------------------------- #
def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[’'\-]", "", text)
    return re.sub(r"[^a-z0-9 ]+", " ", text).strip()


def find_wake_word(text: str, name: str, sensitivity: float = 0.78, search_window: int = 4):
    """Cherche le prénom au début de la phrase (tolère les erreurs de transcription,
    ex. « c'est lia » pour « Celia »). Retourne la suite de la phrase, ou None."""
    words = text.split()
    norm = [normalize(w) for w in words]
    target = normalize(name).replace(" ", "")
    if not target or not words:
        return None
    best = None
    for i in range(min(search_window, len(words))):
        for span in (1, 2, 3):           # le prénom peut être découpé en plusieurs mots
            if i + span > len(words):
                break
            cand = "".join(norm[i:i + span])
            if not cand:
                continue
            ratio = difflib.SequenceMatcher(None, cand, target).ratio()
            if ratio >= sensitivity and (best is None or ratio > best[0]):
                best = (ratio, i + span)
        if best and best[0] >= 0.95:
            break
    if best is None:
        return None
    return " ".join(words[best[1]:]).strip()


# --------------------------------------------------------------------------- #
#  Écoute du micro
# --------------------------------------------------------------------------- #
class Listener:
    """Écoute le micro en continu et transmet chaque phrase reconnue à on_text."""

    def __init__(self, model_dir: Path, on_text, on_partial=lambda t: None, on_error=lambda e: None):
        import vosk
        vosk.SetLogLevel(-1)
        self._vosk = vosk
        self.model = vosk.Model(str(model_dir))
        self.on_text, self.on_partial, self.on_error = on_text, on_partial, on_error
        self._q = queue.Queue()
        self._stream = None
        self._running = False
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    @property
    def active(self):
        return self._running

    def start(self):
        import sounddevice as sd
        with self._lock:
            if self._running:
                return
            self._rec = self._vosk.KaldiRecognizer(self.model, SAMPLE_RATE)
            self._stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000, dtype="int16",
                                             channels=1, callback=self._callback)
            self._stream.start()
            self._running = True

    def stop(self):
        with self._lock:
            self._running = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            while not self._q.empty():
                self._q.get_nowait()

    def _callback(self, indata, frames, time_info, status):
        if self._running:
            self._q.put(bytes(indata))

    def _loop(self):
        while True:
            data = self._q.get()
            if not self._running:
                continue
            try:
                if self._rec.AcceptWaveform(data):
                    text = json.loads(self._rec.Result()).get("text", "").strip()
                    if text:
                        self.on_text(text)
                else:
                    partial = json.loads(self._rec.PartialResult()).get("partial", "")
                    if partial:
                        self.on_partial(partial)
            except Exception as e:  # ne jamais tuer la boucle d'écoute
                self.on_error(e)


# --------------------------------------------------------------------------- #
#  Synthèse vocale
# --------------------------------------------------------------------------- #
class SystemSpeaker:
    """Synthèse vocale hors-ligne (voix du système, Windows / Linux), dans son propre fil d'exécution."""

    def __init__(self, voice_id: str = "", rate: int = 185):
        self._q = queue.Queue()
        self._stop_flag = False
        self.speaking = False
        self.voices = []          # [(id, nom)]
        self._ready = threading.Event()
        self._voice_id, self._rate = voice_id, rate
        threading.Thread(target=self._loop, daemon=True).start()
        self._ready.wait(timeout=10)

    def configure(self, voice_id: str = None, rate: int = None):
        self._q.put(("config", voice_id, rate))

    def say(self, text: str, on_done=None):
        self._q.put(("say", text, on_done))

    def interrupt(self):
        self._stop_flag = True
        while True:  # vide la file d'attente
            try:
                item = self._q.get_nowait()
            except queue.Empty:
                break
            if item[0] == "config":
                self._q.put(item)
                break

    # -- fil interne -------------------------------------------------------- #
    def _apply(self, engine, voice_id, rate):
        if rate:
            engine.setProperty("rate", int(rate))
        if voice_id:
            engine.setProperty("voice", voice_id)

    def _loop(self):
        if sys.platform == "win32":
            try:
                import comtypes
                comtypes.CoInitialize()
            except Exception:
                pass
        try:
            import pyttsx3
            engine = pyttsx3.init()
        except Exception as e:
            print("Synthèse vocale indisponible :", e)
            engine = None
        if engine:
            for v in engine.getProperty("voices"):
                self.voices.append((v.id, v.name))
            vid = self._voice_id or self._pick_french_voice(engine)
            self._apply(engine, vid, self._rate)

            def on_word(name, location, length):
                if self._stop_flag:
                    engine.stop()
            engine.connect("started-word", on_word)
        self._ready.set()

        while True:
            item = self._q.get()
            if item[0] == "config":
                if engine:
                    self._apply(engine, item[1], item[2])
                continue
            _, text, on_done = item
            self._stop_flag = False
            self.speaking = True
            try:
                if engine:
                    engine.say(text)
                    engine.runAndWait()
            except Exception as e:
                print("Erreur de synthèse vocale :", e)
            finally:
                self.speaking = False
                if on_done:
                    on_done()

    @staticmethod
    def _pick_french_voice(engine):
        for v in engine.getProperty("voices"):
            blob = f"{v.id} {v.name} {getattr(v, 'languages', '')}".lower()
            if "fr" in blob and ("french" in blob or "fran" in blob or "fr-" in blob or "fr_" in blob):
                return v.id
        return None


class MacSpeaker:
    """Synthèse vocale macOS avec la commande « say » : accès à toutes les voix du Mac,
    y compris les voix « Premium » et « Améliorée » de haute qualité."""

    def __init__(self, voice_id: str = "", rate: int = 185):
        import subprocess
        self._sp = subprocess
        self._q = queue.Queue()
        self._proc = None
        self.speaking = False
        self.voices = self._list_voices()          # [(nom, "nom — langue")]
        self._voice = voice_id or self._best_french()
        self._rate = rate
        threading.Thread(target=self._loop, daemon=True).start()

    def _list_voices(self):
        try:
            out = self._sp.run(["say", "-v", "?"], capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return []
        voices = []
        for line in out.splitlines():
            m = re.match(r"^(.+?)\s+([a-z]{2,3}_[A-Za-z0-9]+)\s+#", line)
            if m:
                voices.append((m.group(1).strip(), m.group(2)))
        # les voix françaises d'abord
        voices.sort(key=lambda v: (not v[1].startswith("fr"), v[0].lower()))
        return [(name, f"{name} — {lang}") for name, lang in voices]

    def _best_french(self):
        names = [v[0] for v in self.voices if "— fr" in v[1]]
        for wanted in ("premium", "améliorée", "enhanced", "amélioré"):
            for n in names:
                if wanted in n.lower() and "fr_FR" in dict(self.voices)[n]:
                    return n
        for n in names:
            if "fr_FR" in dict(self.voices)[n]:
                return n
        return names[0] if names else ""

    def configure(self, voice_id: str = None, rate: int = None):
        if voice_id is not None:
            self._voice = voice_id or self._best_french()
        if rate:
            self._rate = rate

    def say(self, text: str, on_done=None):
        self._q.put((text, on_done))

    def interrupt(self):
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break
        p = self._proc
        if p and p.poll() is None:
            p.terminate()

    def _loop(self):
        while True:
            text, on_done = self._q.get()
            self.speaking = True
            try:
                cmd = ["say", "-r", str(int(self._rate))]
                if self._voice:
                    cmd += ["-v", self._voice]
                self._proc = self._sp.Popen(cmd + ["--", text])
                self._proc.wait()
            except Exception as e:
                print("Erreur de synthèse vocale :", e)
            finally:
                self.speaking = False
                if on_done:
                    on_done()


Speaker = MacSpeaker if sys.platform == "darwin" else SystemSpeaker


def beep():
    try:
        if sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["afplay", "/System/Library/Sounds/Tink.aiff"])
        elif sys.platform == "win32":
            import winsound
            winsound.Beep(880, 120)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass
