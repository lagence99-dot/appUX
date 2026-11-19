"""Le « cerveau » de Celia : les questions sont envoyées à Claude via l'API Anthropic."""
import datetime
import re
import time

import anthropic

MODELS = {
    "claude-opus-5-5": "Claude Opus 5.5 (le plus intelligent)",
    "claude-sonnet-5-5": "Claude Sonnet 5.5 (équilibré)",
    "claude-haiku-5-5": "Claude Haiku 5.5 (le plus rapide / économique)",
}
EFFORTS = ["low", "medium", "high"]

MAX_HISTORY_MESSAGES = 30          # mémoire de la conversation (15 échanges)
FORGET_AFTER_SECONDS = 20 * 60     # nouvelle conversation après 20 min de silence

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]

SYSTEM_PROMPT = """Tu es {name}, l'assistante vocale personnelle installée sur l'ordinateur de {user}.
On te parle à voix haute et ta réponse sera lue par une synthèse vocale.

Règles de forme (importantes, car tout est lu à voix haute) :
- Écris uniquement des phrases parlées naturelles : pas de markdown, pas de titres, pas de listes à puces, pas de tableaux, pas d'emojis, pas d'URL.
- Va droit au but : en général deux à quatre phrases. Développe seulement si on te le demande.
- Écris les nombres, unités et abréviations comme on les dirait à l'oral quand cela aide la lecture.
- Réponds dans la langue de la question (le français par défaut).

La transcription de la voix peut contenir des erreurs : interprète la demande de façon raisonnable, et si elle est vraiment incompréhensible, demande simplement de répéter.
Pour l'actualité, la météo, les horaires ou tout ce qui change, utilise la recherche web si elle est disponible.
Tu ne peux pas agir sur l'ordinateur (ouvrir des applications, envoyer des messages) : dis-le simplement si on te le demande.

Date et heure actuelles : {now}."""


def _now_fr() -> str:
    n = datetime.datetime.now()
    return f"{JOURS[n.weekday()]} {n.day} {MOIS[n.month - 1]} {n.year}, {n.hour} h {n.minute:02d}"


def clean_for_speech(text: str) -> str:
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


class Brain:
    def __init__(self, config):
        self.config = config
        self.history = []
        self.last_exchange = 0.0

    def reset(self):
        self.history = []

    def ask(self, question: str) -> str:
        cfg = self.config
        if not cfg.api_key:
            return ("Je n'ai pas encore de clé API. Ouvrez les réglages et collez votre clé "
                    "Anthropic pour que je puisse vous répondre.")
        if time.time() - self.last_exchange > FORGET_AFTER_SECONDS:
            self.history = []

        model = cfg.get("model") or "claude-opus-5-5"
        system = SYSTEM_PROMPT.format(
            name=cfg.get("assistant_name") or "Celia",
            user=cfg.get("user_name") or "l'utilisateur",
            now=_now_fr(),
        )
        params = dict(
            model=model,
            max_tokens=16000,
            system=system,
            output_config={"effort": cfg.get("effort") or "low"},
        )
        if cfg.get("web_search", True):
            search_type = ("web_search_20250305" if model.startswith("claude-haiku")
                           else "web_search_20260209")
            params["tools"] = [{
                "type": search_type,
                "name": "web_search",
                "max_uses": 3,
                "user_location": {"type": "approximate",
                                  "country": (cfg.get("country") or "FR").upper()[:2]},
            }]
        # Opus / Sonnet : si un filtre de sécurité refuse par erreur, l'API bascule
        # automatiquement sur un autre modèle (fallback côté serveur).
        use_fallback = not model.startswith("claude-haiku")
        if use_fallback:
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"

        client = anthropic.Anthropic(api_key=cfg.api_key, timeout=90.0, max_retries=2)
        messages = self.history + [{"role": "user", "content": question}]
        parts = []
        try:
            for _ in range(6):
                if use_fallback:
                    resp = client.beta.messages.create(messages=messages, **params)
                else:
                    resp = client.messages.create(messages=messages, **params)
                if resp.stop_reason == "refusal":
                    return "Désolée, je ne peux pas répondre à cette demande."
                parts += [b.text for b in resp.content if b.type == "text"]
                if resp.stop_reason != "pause_turn":
                    break
                # Recherche web longue : on relance pour laisser Claude terminer.
                messages = messages + [{"role": "assistant", "content": resp.content}]
        except anthropic.AuthenticationError:
            return "Ma clé API semble invalide. Vérifiez-la dans les réglages."
        except anthropic.PermissionDeniedError:
            return "Cette clé API n'a pas accès à ce modèle. Essayez un autre modèle dans les réglages."
        except anthropic.RateLimitError:
            return "Je reçois trop de demandes en ce moment. Réessayez dans quelques instants."
        except anthropic.APIConnectionError:
            return "Je n'arrive pas à me connecter à Internet. Vérifiez votre connexion."
        except anthropic.APIStatusError as e:
            return f"Une erreur est survenue côté serveur, code {e.status_code}. Réessayez dans un instant."

        answer = clean_for_speech(" ".join(parts)) or "Je n'ai pas de réponse à cela."
        # On ne garde que le texte dans la mémoire : simple, léger et robuste.
        self.history += [{"role": "user", "content": question},
                         {"role": "assistant", "content": answer}]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.last_exchange = time.time()
        return answer
