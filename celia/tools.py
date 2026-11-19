"""Outils mis à disposition de Claude pour gérer la mémoire, le planning et les projets."""
import json
from pathlib import Path

from .memory import NOTE_KINDS, fr_date


def _obj(props, required=()):
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


S = {"type": "string"}
DATE = {"type": "string", "description": "Date au format AAAA-MM-JJ (convertis « demain », « vendredi »… "
                                         "à partir de la date du jour)."}
TIME = {"type": "string", "description": "Heure au format HH:MM, si une heure précise est donnée."}
PROJECT = {"type": "string", "description": "Nom du projet concerné, s'il y en a un."}

TOOLS = [
    {"name": "ajouter_tache",
     "description": "Ajoute une tâche, un rendez-vous ou une action à faire au planning. Si une heure est "
                    "donnée, un rappel vocal sera fait à ce moment-là.",
     "input_schema": _obj({"titre": S, "date": DATE, "heure": TIME, "projet": PROJECT}, ["titre"])},
    {"name": "lister_taches",
     "description": "Liste les tâches d'une période (par défaut : à faire). Utile pour une période au-delà "
                    "des 7 jours déjà fournis dans le contexte, ou pour revoir les tâches terminées.",
     "input_schema": _obj({"date_debut": DATE, "date_fin": DATE, "projet": PROJECT,
                           "inclure_terminees": {"type": "boolean"}})},
    {"name": "modifier_tache",
     "description": "Modifie une tâche existante (titre, date, heure, projet) ou la marque terminée / "
                    "à refaire. Utilise l'identifiant (ex. T12) visible dans le planning.",
     "input_schema": _obj({"id": S, "titre": S, "date": DATE, "heure": TIME, "projet": PROJECT,
                           "terminee": {"type": "boolean"}}, ["id"])},
    {"name": "supprimer_tache",
     "description": "Supprime définitivement une tâche (seulement si l'utilisateur le demande).",
     "input_schema": _obj({"id": S}, ["id"])},
    {"name": "retenir",
     "description": "Enregistre durablement une information : une décision prise, une action mise en place, "
                    "une idée ou une note. À utiliser dès que l'utilisateur dit « retiens », « note », ou "
                    "quand une décision importante est prise pendant l'échange.",
     "input_schema": _obj({"texte": S, "type": {"type": "string", "enum": list(NOTE_KINDS)},
                           "projet": PROJECT}, ["texte"])},
    {"name": "rechercher_memoire",
     "description": "Cherche dans tout ce qui a été retenu, les tâches (même terminées) et l'historique des "
                    "conversations passées. À utiliser pour « qu'avait-on dit sur… », « qu'est-ce qu'on a mis "
                    "en place pour… », « on en était où… ».",
     "input_schema": _obj({"recherche": {"type": "string", "description": "Mots-clés."},
                           "projet": PROJECT,
                           "jours": {"type": "integer", "description": "Limiter aux N derniers jours."}})},
    {"name": "creer_projet",
     "description": "Crée un nouveau projet : un dossier sur l'ordinateur avec une fiche PROJET.md "
                    "(objectif, prochaines étapes). Propose des étapes concrètes si l'utilisateur n'en donne pas.",
     "input_schema": _obj({"nom": S, "description": S,
                           "etapes": {"type": "array", "items": S,
                                      "description": "Premières étapes ; elles sont aussi ajoutées au planning."}},
                          ["nom", "description"])},
    {"name": "voir_projet",
     "description": "Donne tout ce qui concerne un projet : description, tâches, notes et décisions.",
     "input_schema": _obj({"nom": S}, ["nom"])},
    {"name": "modifier_projet",
     "description": "Change le statut (ex. en cours, en pause, terminé) ou la description d'un projet.",
     "input_schema": _obj({"nom": S, "statut": S, "description": S}, ["nom"])},
]


def _task_view(t):
    return {"id": t["id"], "titre": t["title"], "quand": fr_date(t["date"]) if t["date"] else "sans date",
            "date": t["date"], "heure": t["time"], "projet": t.get("project"), "terminee": t["done"]}


def execute(memory, config, name, args):
    """Exécute un outil. Retourne (texte_resultat, est_une_erreur)."""
    args = args if isinstance(args, dict) else {}
    try:
        if name == "ajouter_tache":
            t = memory.add_task(args.get("titre"), args.get("date"), args.get("heure"), args.get("projet"))
            return json.dumps({"ok": True, "tache": _task_view(t)}, ensure_ascii=False), False

        if name == "lister_taches":
            tasks = memory.list_tasks(args.get("date_debut"), args.get("date_fin"),
                                      bool(args.get("inclure_terminees")), args.get("projet"))
            return json.dumps({"taches": [_task_view(t) for t in tasks[:60]], "total": len(tasks)},
                              ensure_ascii=False), False

        if name == "modifier_tache":
            t = memory.update_task(args.get("id", ""), title=args.get("titre"), date=args.get("date"),
                                   time=args.get("heure"), project=args.get("projet"),
                                   done=args.get("terminee"))
            return json.dumps({"ok": True, "tache": _task_view(t)}, ensure_ascii=False), False

        if name == "supprimer_tache":
            t = memory.delete_task(args.get("id", ""))
            return json.dumps({"ok": True, "supprimee": t["title"]}, ensure_ascii=False), False

        if name == "retenir":
            n = memory.add_note(args.get("texte"), args.get("type", "note"), args.get("projet"))
            return json.dumps({"ok": True, "id": n["id"]}, ensure_ascii=False), False

        if name == "rechercher_memoire":
            res = memory.recall(args.get("recherche", ""), args.get("projet"), args.get("jours"))
            return json.dumps({"resultats": res} if res else {"resultats": [], "info": "Rien trouvé."},
                              ensure_ascii=False), False

        if name == "creer_projet":
            base = config.get("projects_dir") or str(Path.home() / "Documents" / "Projets")
            p = memory.create_project(args.get("nom"), args.get("description"), base, args.get("etapes"),
                                      assistant=config.get("assistant_name") or "Celia")
            for step in (args.get("etapes") or [])[:10]:
                memory.add_task(step, project=p["name"])
            return json.dumps({"ok": True, "projet": p["name"], "dossier": p["folder"]},
                              ensure_ascii=False), False

        if name == "voir_projet":
            d = memory.project_details(args.get("nom", ""))
            d["taches_a_faire"] = [_task_view(t) for t in d["taches_a_faire"]]
            d["taches_terminees"] = [_task_view(t) for t in d["taches_terminees"]]
            return json.dumps(d, ensure_ascii=False), False

        if name == "modifier_projet":
            p = memory.update_project(args.get("nom", ""), args.get("statut"), args.get("description"))
            return json.dumps({"ok": True, "projet": p}, ensure_ascii=False), False

        return f"Outil inconnu : {name}", True
    except (ValueError, OSError) as e:
        return f"Erreur : {e}", True
