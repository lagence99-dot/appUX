"""Chargement / sauvegarde des réglages de Celia (fichier JSON local)."""
import json
import os
import sys
from pathlib import Path

APP_NAME = "Celia"

DEFAULTS = {
    "assistant_name": "Celia",      # prénom pour l'appeler (mot de réveil)
    "user_name": "",                # votre prénom (facultatif)
    "api_key": "",                  # clé API Anthropic (ou variable ANTHROPIC_API_KEY)
    "model": "claude-opus-5-5",
    "effort": "low",                # low = réponses rapides, idéal pour la voix
    "web_search": True,             # recherche web pour l'actualité, la météo...
    "country": "FR",                # pays pour la recherche web (code ISO)
    "voice_id": "",                 # voix de synthèse ("" = première voix française)
    "speech_rate": 185,             # vitesse de parole
    "wake_sensitivity": 0.78,       # 0.6 = très tolérant, 0.95 = très strict
    "vosk_model_path": "",          # "" = modèle français téléchargé automatiquement
    "start_with_system": False,     # lancement automatique à l'ouverture de session
    "listen_on_start": True,        # écoute active dès le lancement
}


def app_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


class Config(dict):
    path = app_dir() / "config.json"

    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
        except (OSError, ValueError):
            pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(self), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)
        if sys.platform != "win32":
            try:
                os.chmod(self.path, 0o600)  # la clé API reste privée
            except OSError:
                pass

    @property
    def api_key(self) -> str:
        return self.get("api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
