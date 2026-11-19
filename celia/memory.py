"""Mémoire permanente de Celia, stockée sur votre ordinateur.

- tâches et planning (avec date / heure, rappels) ;
- notes : décisions prises, actions mises en place, choses à retenir ;
- projets (avec leur dossier sur le disque) ;
- journal de toutes les conversations, pour pouvoir y revenir plus tard.
"""
import datetime as dt
import json
import os
import re
import threading
from pathlib import Path

from .config import app_dir
from .voice import normalize

JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
NOTE_KINDS = {"note": "Note", "decision": "Décision", "action": "Action mise en place", "idee": "Idée"}

STOP = set("le la les un une des de du d l et ou a au aux en dans pour sur avec que qui quoi est "
           "ce ca cette ces mon ma mes ton ta tes son sa ses on nous vous je tu il elle ils elles "
           "pas ne plus se s y t m n qu c j as ai avait avons".split())


def today() -> dt.date:
    return dt.date.today()


def parse_date(value):
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_time(value):
    if not value:
        return None
    m = re.match(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{0,2})\s*$", str(value))
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mnt > 59:
        return None
    return f"{h:02d}:{mnt:02d}"


def fr_date(d, ref=None) -> str:
    """Date lisible à voix haute : « aujourd'hui », « demain », « vendredi 22 novembre »."""
    if d is None:
        return "sans date"
    if isinstance(d, str):
        d = parse_date(d)
        if d is None:
            return "sans date"
    ref = ref or today()
    delta = (d - ref).days
    if delta == 0:
        return "aujourd'hui"
    if delta == 1:
        return "demain"
    if delta == -1:
        return "hier"
    s = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return s if d.year == ref.year else f"{s} {d.year}"


def say_time(t: str) -> str:
    h, m = t.split(":")
    return f"{int(h)} h" + (f" {m}" if m != "00" else "")


def _words(text: str):
    return {w for w in normalize(text).split() if len(w) > 1 and w not in STOP}


def safe_folder_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip().strip(".")
    return re.sub(r"\s+", " ", name)[:80] or "Nouveau projet"


class Memory:
    def __init__(self, folder=None):
        self.dir = Path(folder) if folder else app_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "memoire.json"
        self.journal_file = self.dir / "journal.jsonl"
        self.lock = threading.RLock()
        self.listeners = []
        self.data = {"next_id": 1, "tasks": [], "notes": [], "projects": [], "last_briefing": ""}
        try:
            with open(self.file, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------------ #
    def _save(self):
        tmp = self.file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.file)
        for cb in list(self.listeners):
            try:
                cb()
            except Exception:
                pass

    def _new_id(self, prefix):
        n = self.data["next_id"]
        self.data["next_id"] = n + 1
        return f"{prefix}{n}"

    @staticmethod
    def _now():
        return dt.datetime.now().isoformat(timespec="minutes")

    # ------------------------------------------------------------------ #
    #  Tâches / planning
    # ------------------------------------------------------------------ #
    def add_task(self, title, date=None, time=None, project=None):
        title = (title or "").strip()
        if not title:
            raise ValueError("La tâche n'a pas de titre.")
        d = parse_date(date)
        t = parse_time(time)
        if t and not d:
            d = today()
        task = {"id": self._new_id("T"), "title": title, "date": d.isoformat() if d else None,
                "time": t, "project": (project or "").strip() or None, "done": False,
                "created": self._now(), "done_at": None, "reminded": False}
        with self.lock:
            self.data["tasks"].append(task)
            self._save()
        return task

    def find_task(self, task_id):
        tid = str(task_id).strip().upper()
        if tid and not tid.startswith("T"):
            tid = "T" + tid
        for t in self.data["tasks"]:
            if t["id"] == tid:
                return t
        return None

    def update_task(self, task_id, **fields):
        with self.lock:
            t = self.find_task(task_id)
            if not t:
                raise ValueError(f"Tâche {task_id} introuvable.")
            if fields.get("title"):
                t["title"] = fields["title"].strip()
            if "date" in fields and fields["date"] is not None:
                d = parse_date(fields["date"])
                t["date"] = d.isoformat() if d else None
                t["reminded"] = False
            if "time" in fields and fields["time"] is not None:
                t["time"] = parse_time(fields["time"])
                t["reminded"] = False
            if "project" in fields and fields["project"] is not None:
                t["project"] = fields["project"].strip() or None
            if "done" in fields and fields["done"] is not None:
                t["done"] = bool(fields["done"])
                t["done_at"] = self._now() if t["done"] else None
            self._save()
            return t

    def complete_task(self, task_id):
        return self.update_task(task_id, done=True)

    def delete_task(self, task_id):
        with self.lock:
            t = self.find_task(task_id)
            if not t:
                raise ValueError(f"Tâche {task_id} introuvable.")
            self.data["tasks"].remove(t)
            self._save()
            return t

    def list_tasks(self, start=None, end=None, include_done=False, project=None, include_undated=True):
        start, end = parse_date(start), parse_date(end)
        out = []
        for t in self.data["tasks"]:
            if t["done"] and not include_done:
                continue
            if project and normalize(project) not in normalize(t.get("project") or ""):
                continue
            d = parse_date(t["date"])
            if d is None:
                if include_undated:
                    out.append(t)
                continue
            if start and d < start:
                continue
            if end and d > end:
                continue
            out.append(t)
        return sorted(out, key=lambda t: (t["date"] or "9999", t["time"] or "99", t["id"]))

    def overdue(self):
        ref = today()
        return [t for t in self.list_tasks(include_undated=False)
                if parse_date(t["date"]) < ref]

    def due_reminders(self, now=None):
        """Tâches dont l'heure est arrivée (aujourd'hui) et pas encore rappelées."""
        now = now or dt.datetime.now()
        due = []
        with self.lock:
            for t in self.data["tasks"]:
                if t["done"] or t["reminded"] or not t["time"] or not t["date"]:
                    continue
                when = dt.datetime.fromisoformat(f"{t['date']}T{t['time']}")
                if when <= now and (now - when) < dt.timedelta(hours=12):
                    t["reminded"] = True
                    due.append(t)
            if due:
                self._save()
        return due

    # ------------------------------------------------------------------ #
    #  Notes, décisions, actions
    # ------------------------------------------------------------------ #
    def add_note(self, text, kind="note", project=None):
        text = (text or "").strip()
        if not text:
            raise ValueError("Rien à retenir.")
        kind = kind if kind in NOTE_KINDS else "note"
        note = {"id": self._new_id("N"), "text": text, "kind": kind,
                "project": (project or "").strip() or None, "date": self._now()}
        with self.lock:
            self.data["notes"].append(note)
            self._save()
        return note

    def delete_note(self, note_id):
        with self.lock:
            nid = str(note_id).strip().upper()
            for n in self.data["notes"]:
                if n["id"] == nid:
                    self.data["notes"].remove(n)
                    self._save()
                    return n
        raise ValueError(f"Note {note_id} introuvable.")

    # ------------------------------------------------------------------ #
    #  Projets
    # ------------------------------------------------------------------ #
    def find_project(self, name):
        target = normalize(name or "")
        if not target:
            return None
        for p in self.data["projects"]:
            if normalize(p["name"]) == target:
                return p
        for p in self.data["projects"]:
            if target in normalize(p["name"]) or normalize(p["name"]) in target:
                return p
        return None

    def create_project(self, name, description, base_dir, steps=None, assistant="Celia"):
        name = (name or "").strip()
        if not name:
            raise ValueError("Le projet n'a pas de nom.")
        if self.find_project(name):
            raise ValueError(f"Le projet « {name} » existe déjà.")
        base = Path(base_dir).expanduser()
        folder = base / safe_folder_name(name)
        n = 2
        while folder.exists():
            folder = base / f"{safe_folder_name(name)} ({n})"
            n += 1
        folder.mkdir(parents=True)
        (folder / "documents").mkdir()
        steps = [s for s in (steps or []) if str(s).strip()]
        lines = [f"# {name}", "", f"*Projet créé le {today().day} {MOIS[today().month - 1]} {today().year} avec {assistant}.*", "",
                 "## Objectif", "", (description or "").strip() or "À préciser.", ""]
        if steps:
            lines += ["## Prochaines étapes", ""] + [f"- [ ] {s}" for s in steps] + [""]
        lines += ["## Journal", "", f"- {today().isoformat()} : création du projet.", ""]
        (folder / "PROJET.md").write_text("\n".join(lines), encoding="utf-8")
        project = {"id": self._new_id("P"), "name": name, "description": (description or "").strip(),
                   "folder": str(folder), "created": self._now(), "status": "en cours"}
        with self.lock:
            self.data["projects"].append(project)
            self._save()
        return project

    def update_project(self, name, status=None, description=None):
        with self.lock:
            p = self.find_project(name)
            if not p:
                raise ValueError(f"Projet « {name} » introuvable.")
            if status:
                p["status"] = status
            if description:
                p["description"] = description
            self._save()
            return p

    def project_details(self, name):
        p = self.find_project(name)
        if not p:
            raise ValueError(f"Projet « {name} » introuvable.")
        key = normalize(p["name"])
        tasks = [t for t in self.data["tasks"] if normalize(t.get("project") or "") == key]
        notes = [n for n in self.data["notes"] if normalize(n.get("project") or "") == key]
        return {"projet": p,
                "taches_a_faire": [t for t in tasks if not t["done"]],
                "taches_terminees": [t for t in tasks if t["done"]][-10:],
                "notes": notes[-20:]}

    # ------------------------------------------------------------------ #
    #  Journal des conversations + recherche
    # ------------------------------------------------------------------ #
    def log_exchange(self, question, answer):
        with self.lock:
            with open(self.journal_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"date": self._now(), "question": question, "reponse": answer},
                                   ensure_ascii=False) + "\n")

    def _journal(self):
        try:
            with open(self.journal_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        yield json.loads(line)
                    except ValueError:
                        continue
        except OSError:
            return

    def recall(self, query="", project=None, days=None, limit=10):
        """Recherche dans les notes, les tâches (y compris terminées) et le journal."""
        q = _words(query or "")
        since = (dt.datetime.now() - dt.timedelta(days=int(days))) if days else None
        results = []

        def consider(kind, date, text, extra):
            if since and date and dt.datetime.fromisoformat(date[:16]) < since:
                return
            if project and normalize(project) not in normalize(extra.get("project") or "") \
                    and normalize(project) not in normalize(text):
                return
            score = len(q & _words(text)) if q else 1
            if score:
                results.append((score, date or "", {"type": kind, "date": date, "texte": text, **extra}))

        for n in self.data["notes"]:
            consider(NOTE_KINDS.get(n["kind"], "Note"), n["date"], n["text"],
                     {"id": n["id"], "project": n.get("project")})
        for t in self.data["tasks"]:
            consider("Tâche terminée" if t["done"] else "Tâche", t["created"], t["title"],
                     {"id": t["id"], "project": t.get("project"), "prevue": t["date"]})
        for e in self._journal():
            consider("Conversation", e["date"], f"Question : {e['question']} | Réponse : {e['reponse']}", {})

        results.sort(key=lambda r: (r[0], r[1]), reverse=True)
        return [r[2] for r in results[:limit]]

    # ------------------------------------------------------------------ #
    #  Résumés
    # ------------------------------------------------------------------ #
    @staticmethod
    def _task_line(t, ref):
        when = fr_date(t["date"], ref) if t["date"] else "sans date"
        if t["time"]:
            when += f" à {say_time(t['time'])}"
        proj = f" [projet {t['project']}]" if t.get("project") else ""
        return f"- {t['id']} : {t['title']} ({when}){proj}"

    def context_summary(self) -> str:
        """Résumé injecté dans chaque requête : Celia connaît ainsi votre planning."""
        ref = today()
        lines = []
        late = self.overdue()
        if late:
            lines.append("En retard :")
            lines += [self._task_line(t, ref) for t in late[:15]]
        week = self.list_tasks(ref, ref + dt.timedelta(days=7), include_undated=False)
        lines.append("Planning des 7 prochains jours :" if week else "Aucune tâche prévue dans les 7 prochains jours.")
        lines += [self._task_line(t, ref) for t in week[:40]]
        undated = [t for t in self.list_tasks() if not t["date"]]
        if undated:
            lines.append("À faire, sans date :")
            lines += [self._task_line(t, ref) for t in undated[:15]]
        later = self.list_tasks(ref + dt.timedelta(days=8), None, include_undated=False)
        if later:
            lines.append(f"Plus tard : {len(later)} tâche(s) (utilise lister_taches pour les voir).")
        done_recent = [t for t in self.data["tasks"] if t["done"] and t["done_at"]
                       and t["done_at"][:10] >= (ref - dt.timedelta(days=2)).isoformat()]
        if done_recent:
            lines.append("Terminé récemment :")
            lines += [f"- {t['title']} (terminé {fr_date(t['done_at'][:10], ref)})" for t in done_recent[-10:]]
        if self.data["projects"]:
            lines.append("Projets : " + "; ".join(
                f"{p['name']} ({p['status']})" for p in self.data["projects"][-20:]))
        notes = self.data["notes"][-12:]
        if notes:
            lines.append("Dernières choses retenues :")
            lines += [f"- {fr_date(n['date'][:10], ref)}, {NOTE_KINDS.get(n['kind'], 'Note').lower()}"
                      f"{' [projet ' + n['project'] + ']' if n.get('project') else ''} : {n['text']}"
                      for n in notes]
        return "\n".join(lines)

    def briefing(self, user_name="") -> str:
        """Point du matin, construit localement (gratuit, sans appel à Claude)."""
        ref = today()
        hello = f"Bonjour {user_name} !" if user_name else "Bonjour !"
        parts = [f"{hello} Nous sommes {fr_date(ref, ref - dt.timedelta(days=7))}."]
        late = self.overdue()
        todays = self.list_tasks(ref, ref, include_undated=False)
        tomorrow = self.list_tasks(ref + dt.timedelta(days=1), ref + dt.timedelta(days=1), include_undated=False)

        def say_list(tasks):
            items = [t["title"] + (f" à {say_time(t['time'])}" if t["time"] else "") for t in tasks[:6]]
            s = ", ".join(items[:-1]) + (" et " if len(items) > 1 else "") + items[-1]
            return s + (f", plus {len(tasks) - 6} autres" if len(tasks) > 6 else "")

        if todays:
            parts.append(f"Aujourd'hui, tu as {len(todays)} chose{'s' if len(todays) > 1 else ''} "
                         f"de prévue{'s' if len(todays) > 1 else ''} : {say_list(todays)}.")
        else:
            parts.append("Rien n'est prévu aujourd'hui pour l'instant.")
        if late:
            parts.append(f"Il reste aussi {len(late)} tâche{'s' if len(late) > 1 else ''} en retard : "
                         f"{say_list(late)}.")
        if tomorrow:
            parts.append(f"Demain : {say_list(tomorrow)}.")
        parts.append("Dis-moi si tu veux qu'on organise la journée.")
        return " ".join(parts)
