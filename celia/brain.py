"""Le « cerveau » de Celia.

Trois moteurs possibles :
- « claude » : Claude via l'API Anthropic (le meilleur ; nécessite une clé et du crédit) ;
- « ollama » : une IA gratuite qui tourne sur l'ordinateur (https://ollama.com) ;
- « demo »   : mode test gratuit, sans IA (heure, date, planning) pour vérifier micro et voix.
"""
import datetime
import re
import time

import anthropic

from . import local_ai
from .tools import TOOLS, execute

ENGINES = {
    "auto": "Automatique (Claude si une clé est saisie, sinon gratuit)",
    "claude": "Claude — API Anthropic (le meilleur, payant)",
    "ollama": "Ollama — IA gratuite sur cet ordinateur",
    "demo": "Démo — test gratuit sans IA",
}

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

SYSTEM_PROMPT = """Tu es {name}, l'assistante vocale personnelle de {user}, installée sur son ordinateur.
On te parle à voix haute et ta réponse sera lue par une synthèse vocale. Tu tutoies {user}.

Règles de forme (importantes, car tout est lu à voix haute) :
- Écris uniquement des phrases parlées naturelles : pas de markdown, pas de titres, pas de listes à puces, pas de tableaux, pas d'emojis, pas d'URL.
- Va droit au but : en général deux à quatre phrases. Développe seulement si on te le demande.
- Ne lis jamais les identifiants techniques (T12, N4…) à voix haute.
- Réponds dans la langue de la question (le français par défaut).

Ton rôle : répondre aux questions, mais aussi être la secrétaire et la partenaire de projets de {user}.
- Tu as une mémoire permanente (planning, décisions, actions mises en place, projets, conversations passées). Le planning et ce que tu as retenu récemment sont résumés plus bas : sers-t'en directement pour « qu'est-ce que j'ai aujourd'hui / demain ».
- Quand {user} te demande de noter, planifier ou de lui rappeler quelque chose, utilise tes outils, puis confirme brièvement (quoi et quand).
- Quand une décision est prise ou qu'une action est mise en place pendant l'échange, enregistre-la avec l'outil retenir, sans le demander à chaque fois.
- Pour une question sur le passé (« qu'avait-on décidé pour… », « on en était où… »), cherche avec rechercher_memoire avant de répondre.
- Pour un nouveau projet, crée-le avec creer_projet en proposant trois à cinq premières étapes concrètes.
- N'invente jamais une tâche ou un souvenir : si tu ne trouves rien, dis-le.

La transcription de la voix peut contenir des erreurs : interprète la demande de façon raisonnable, et si elle est vraiment incompréhensible, demande de répéter.
Pour l'actualité, la météo ou tout ce qui change, utilise la recherche web si elle est disponible.

Date et heure actuelles : {now} (date ISO : {iso}).

=== Mémoire de {user} ===
{memory}"""


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
    def __init__(self, config, memory):
        self.config = config
        self.memory = memory
        self.history = []
        self.last_exchange = 0.0
        self._last_error = ""

    def reset(self):
        self.history = []

    def engine(self) -> str:
        """Moteur effectivement utilisé."""
        choice = self.config.get("engine") or "auto"
        if choice != "auto":
            return choice
        if self.config.api_key:
            return "claude"
        return "ollama" if local_ai.is_running() else "demo"

    def _system_prompt(self) -> str:
        cfg = self.config
        return SYSTEM_PROMPT.format(
            name=cfg.get("assistant_name") or "Celia",
            user=cfg.get("user_name") or "l'utilisateur",
            now=_now_fr(),
            iso=datetime.date.today().isoformat(),
            memory=self.memory.context_summary() or "(vide pour l'instant)",
        )

    def ask(self, question: str) -> str:
        if time.time() - self.last_exchange > FORGET_AFTER_SECONDS:
            self.history = []
        engine = self.engine()
        if engine == "demo":
            return self._ask_demo(question)  # rien à mémoriser : pas de vraie conversation
        answer = self._ask_ollama(question) if engine == "ollama" else self._ask_claude(question)
        if answer is None:
            return self._last_error
        answer = clean_for_speech(answer) or "Je n'ai pas de réponse à cela."
        # On ne garde que le texte dans la mémoire : simple, léger et robuste.
        self.history += [{"role": "user", "content": question},
                         {"role": "assistant", "content": answer}]
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        self.last_exchange = time.time()
        try:
            self.memory.log_exchange(question, answer)
        except OSError:
            pass
        return answer

    def _fail(self, message):
        self._last_error = message
        return None

    # ------------------------------------------------------------------ #
    def _ask_claude(self, question):
        cfg = self.config
        if not cfg.api_key:
            return self._fail("Je n'ai pas de clé API Anthropic. Ajoutez-la dans les réglages, "
                              "ou choisissez un moteur gratuit.")
        model = cfg.get("model") or "claude-opus-5-5"
        system = self._system_prompt()
        params = dict(
            model=model,
            max_tokens=16000,
            system=system,
            output_config={"effort": cfg.get("effort") or "low"},
            tools=list(TOOLS),
        )
        if cfg.get("web_search", True):
            search_type = ("web_search_20250305" if model.startswith("claude-haiku")
                           else "web_search_20260209")
            params["tools"].append({
                "type": search_type,
                "name": "web_search",
                "max_uses": 3,
                "user_location": {"type": "approximate",
                                  "country": (cfg.get("country") or "FR").upper()[:2]},
            })
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
            for _ in range(12):
                if use_fallback:
                    resp = client.beta.messages.create(messages=messages, **params)
                else:
                    resp = client.messages.create(messages=messages, **params)
                if resp.stop_reason == "refusal":
                    return self._fail("Désolée, je ne peux pas répondre à cette demande.")
                parts += [b.text for b in resp.content if b.type == "text"]
                if resp.stop_reason == "tool_use":
                    # Claude utilise la mémoire : on exécute ses outils et on lui renvoie les résultats.
                    results = []
                    for b in resp.content:
                        if b.type == "tool_use":
                            out, is_error = execute(self.memory, cfg, b.name, b.input)
                            results.append({"type": "tool_result", "tool_use_id": b.id,
                                            "content": out, "is_error": is_error})
                    messages = messages + [{"role": "assistant", "content": resp.content},
                                           {"role": "user", "content": results}]
                    parts = []  # seule la réponse finale est lue à voix haute
                    continue
                if resp.stop_reason != "pause_turn":
                    break
                # Recherche web longue : on relance pour laisser Claude terminer.
                messages = messages + [{"role": "assistant", "content": resp.content}]
        except anthropic.AuthenticationError:
            return self._fail("Ma clé API semble invalide. Vérifiez-la dans les réglages.")
        except anthropic.PermissionDeniedError:
            return self._fail("Cette clé API n'a pas accès à ce modèle. Essayez un autre modèle dans les réglages.")
        except anthropic.RateLimitError:
            return self._fail("Je reçois trop de demandes en ce moment. Réessayez dans quelques instants.")
        except anthropic.APIConnectionError:
            return self._fail("Je n'arrive pas à me connecter à Internet. Vérifiez votre connexion.")
        except anthropic.BadRequestError as e:
            if "credit" in str(e).lower():
                return self._fail("Le crédit de votre compte Anthropic est épuisé. Rechargez-le sur la console "
                                  "Anthropic, ou passez sur un moteur gratuit dans les réglages.")
            return self._fail("Ma demande a été refusée par le serveur. Réessayez autrement.")
        except anthropic.APIStatusError as e:
            return self._fail(f"Une erreur est survenue côté serveur, code {e.status_code}. "
                              "Réessayez dans un instant.")
        return " ".join(parts)

    # ------------------------------------------------------------------ #
    def _ask_ollama(self, question):
        model = self.config.get("ollama_model") or local_ai.DEFAULT_MODEL
        if not local_ai.is_running():
            return self._fail("L'IA gratuite Ollama n'est pas lancée. Ouvrez l'application Ollama, "
                              "ou installez-la depuis ollama.com.")
        if not local_ai.has_model(model):
            return self._fail("L'IA gratuite est encore en cours d'installation. Réessayez dans quelques minutes.")
        try:
            return local_ai.chat(model, self._system_prompt(), self.history, question, TOOLS,
                                 lambda name, args: execute(self.memory, self.config, name, args))
        except Exception as e:
            return self._fail(f"L'IA gratuite a rencontré un problème : {e}")

    # ------------------------------------------------------------------ #
    def _ask_demo(self, question):
        """Mode test sans IA : quelques réponses locales pour vérifier micro, voix et planning."""
        from .memory import fr_date
        q = re.sub(r"[^a-z0-9 ]", " ", question.lower().replace("é", "e").replace("è", "e")
                   .replace("ê", "e").replace("à", "a").replace("ç", "c"))
        today = datetime.date.today()
        if "heure" in q:
            n = datetime.datetime.now()
            return f"Il est {n.hour} heures {n.minute:02d}."
        if "date" in q or "quel jour" in q or "on est quel" in q:
            return f"Nous sommes {fr_date(today, today - datetime.timedelta(days=7))} {today.year}."
        if "demain" in q and ("planning" in q or "faire" in q or "prevu" in q or "programme" in q):
            tasks = self.memory.list_tasks(today + datetime.timedelta(days=1),
                                           today + datetime.timedelta(days=1), include_undated=False)
            if not tasks:
                return "Rien n'est prévu pour demain."
            return "Demain : " + ", ".join(t["title"] for t in tasks) + "."
        if any(w in q for w in ("planning", "faire", "prevu", "programme", "agenda", "taches")):
            return self.memory.briefing(self.config.get("user_name", "")).replace("Bonjour", "Alors", 1)
        if "bonjour" in q or "salut" in q or "coucou" in q:
            return "Bonjour ! Je t'entends bien. Je suis en mode démo pour l'instant."
        return ("Je t'ai bien entendu ! Je suis en mode démo gratuit : je sais donner l'heure, la date et "
                "ton planning. Pour de vraies conversations, installe l'IA gratuite Ollama, ou ajoute "
                "une clé Claude dans mes réglages.")
