"""Interface et chef d'orchestre de Celia."""
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from . import system
from .brain import EFFORTS, MODELS, Brain
from .config import Config
from .memory import NOTE_KINDS, Memory, fr_date
from .voice import Speaker, beep, ensure_vosk_model, find_wake_word, normalize

FOLLOW_UP_SECONDS = 8   # après « Oui ? », délai pour poser la question

STOP_WORDS = {"stop", "arrete", "arrete toi", "tais toi", "silence", "chut", "ca suffit"}
SLEEP_RE = re.compile(r"\b(mets toi en (veille|pause)|desactive toi|va dormir)\b")
RESET_RE = re.compile(r"\b(nouvelle conversation|oublie tout|on recommence)\b")

FONT = "Helvetica Neue" if sys.platform == "darwin" else "Segoe UI"
IS_MAC = sys.platform == "darwin"
BG, PANEL, FG, MUTED = "#15151c", "#20202a", "#ececf1", "#9a9aab"
ON, OFF, ACCENT = "#2ecc71", "#5a5a66", "#7c5cff"


class CeliaApp:
    def __init__(self, start_toggled_off=False):
        self.cfg = Config()
        self.memory = Memory()
        self.brain = Brain(self.cfg, self.memory)
        self.planning_win = None
        self.ui_q = queue.Queue()
        self.listener = None
        self.speaker = None
        self.awaiting_until = 0.0
        self.busy = False
        self.tray = None
        self.want_listening = self.cfg.get("listen_on_start", True) and not start_toggled_off

        self.root = tk.Tk()
        self.root.title(self.name)
        self.root.geometry("440x640")
        self.root.minsize(380, 520)
        self.root.configure(bg=BG)
        try:
            from PIL import ImageTk
            self._icon_img = ImageTk.PhotoImage(system.make_icon(True, 64))
            self.root.iconphoto(True, self._icon_img)
        except Exception:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        if IS_MAC:
            # Cmd+Q quitte, un clic sur l'icône du Dock rouvre la fenêtre.
            self.root.createcommand("tk::mac::Quit", self.quit)
            self.root.createcommand("tk::mac::ReopenApplication", self.show_window)
        self._build_ui()
        self.root.after(100, self._pump)

        threading.Thread(target=self._init_voice, daemon=True).start()
        self._start_tray()
        self.memory.listeners.append(lambda: self.ui(self._refresh_planning))
        self.root.after(2500, self._morning_briefing)
        self.root.after(15000, self._check_reminders)
        if not self.cfg.api_key:
            self.root.after(600, lambda: self.open_settings(first_run=True))

    # ------------------------------------------------------------------ #
    @property
    def name(self):
        return (self.cfg.get("assistant_name") or "Celia").strip()

    def ui(self, fn, *args):
        """Exécute fn dans le fil de l'interface (thread-safe)."""
        self.ui_q.put((fn, args))

    def _pump(self):
        try:
            while True:
                fn, args = self.ui_q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    # ------------------------------------------------------------------ #
    #  Interface
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG,
                        arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", FG)],
                  selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", FG)])

        self.title_lbl = tk.Label(self.root, text=self.name, font=(FONT, 26, "bold"),
                                  bg=BG, fg=FG)
        self.title_lbl.pack(pady=(18, 0))

        self.canvas = tk.Canvas(self.root, width=150, height=150, bg=BG, highlightthickness=0,
                                cursor="hand2")
        self.canvas.pack(pady=10)
        self.canvas.bind("<Button-1>", lambda e: self.toggle())
        self._draw_button()

        self.status_lbl = tk.Label(self.root, text="Démarrage…", font=(FONT, 11),
                                   bg=BG, fg=MUTED, wraplength=400)
        self.status_lbl.pack()
        self.heard_lbl = tk.Label(self.root, text="", font=(FONT, 9, "italic"),
                                  bg=BG, fg=MUTED, wraplength=400)
        self.heard_lbl.pack(pady=(2, 8))

        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=14)
        self.log = tk.Text(frame, bg=PANEL, fg=FG, relief="flat", wrap="word",
                           font=(FONT, 10), padx=10, pady=8, state="disabled")
        sb = tk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("you", foreground="#8fd3ff", font=(FONT, 10, "bold"))
        self.log.tag_configure("celia", foreground="#c9b8ff", font=(FONT, 10, "bold"))
        self.log.tag_configure("info", foreground=MUTED, font=(FONT, 9, "italic"))

        entry_row = tk.Frame(self.root, bg=BG)
        entry_row.pack(fill="x", padx=14, pady=8)
        self.entry = tk.Entry(entry_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                              font=(FONT, 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self._send_typed())
        self._btn(entry_row, "Envoyer", self._send_typed).pack(side="left", padx=(6, 0))

        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=14, pady=(0, 6))
        self._btn(row, "⏹ Interrompre", self.interrupt).pack(side="left")
        self._btn(row, "↺ Nouvelle conversation", self.new_conversation).pack(side="left", padx=6)
        row2 = tk.Frame(self.root, bg=BG)
        row2.pack(fill="x", padx=14, pady=(0, 14))
        self._btn(row2, "📋 Planning & mémoire", self.open_planning).pack(side="left")
        self._btn(row2, "⚙ Réglages", self.open_settings).pack(side="right")

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=FG, relief="flat",
                         activebackground=ACCENT, activeforeground="white",
                         font=(FONT, 9), padx=10, pady=5, cursor="hand2")

    def _draw_button(self):
        c = self.canvas
        c.delete("all")
        on = self.listener is not None and self.listener.active
        color = ON if on else OFF
        c.create_oval(8, 8, 142, 142, fill=color, outline="")
        c.create_oval(22, 22, 128, 128, outline="white", width=3)
        c.create_text(75, 66, text="ON" if on else "OFF", fill="white", font=(FONT, 22, "bold"))
        c.create_text(75, 96, text="cliquer pour " + ("couper" if on else "activer"),
                      fill="white", font=(FONT, 8))

    def set_status(self, text):
        self.status_lbl.config(text=text)

    def add_log(self, who, text):
        self.log.configure(state="normal")
        if who == "info":
            self.log.insert("end", text + "\n\n", "info")
        else:
            tag = "you" if who == "you" else "celia"
            label = "Vous" if who == "you" else self.name
            self.log.insert("end", f"{label} : ", tag)
            self.log.insert("end", text + "\n\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def idle_status(self):
        if self.listener is None:
            return
        if self.listener.active:
            self.set_status(f"À l'écoute — dites « {self.name} » suivi de votre question")
        else:
            self.set_status("Écoute désactivée (micro coupé)")

    # ------------------------------------------------------------------ #
    #  Voix
    # ------------------------------------------------------------------ #
    def _init_voice(self):
        self.speaker = Speaker(self.cfg.get("voice_id", ""), self.cfg.get("speech_rate", 185))
        try:
            model_dir = ensure_vosk_model(self.cfg.get("vosk_model_path", ""),
                                          progress=lambda m: self.ui(self.set_status, m))
            self.ui(self.set_status, "Chargement de la reconnaissance vocale…")
            from .voice import Listener
            self.listener = Listener(model_dir, self.on_heard,
                                     on_partial=lambda t: self.ui(self.heard_lbl.config, {"text": f"… {t}"}),
                                     on_error=lambda e: print("Écoute :", e))
        except Exception as e:
            self.ui(self.set_status, "Reconnaissance vocale indisponible — vous pouvez écrire vos questions.")
            self.ui(self.add_log, "info", f"Détail : {e}")
            return
        if self.want_listening:
            self.ui(self.start_listening)
        else:
            self.ui(self.idle_status)
            self.ui(self._draw_button)

    def start_listening(self):
        if self.listener is None:
            return
        try:
            self.listener.start()
        except Exception as e:
            self.set_status("Impossible d'ouvrir le micro.")
            self.add_log("info", f"Micro : {e}")
        self._refresh_state()

    def stop_listening(self):
        if self.listener is not None:
            self.listener.stop()
        self.awaiting_until = 0
        self._refresh_state()

    def toggle(self):
        if self.listener is None:
            self.want_listening = not self.want_listening
            self.set_status("La reconnaissance vocale se prépare…")
            return
        if self.listener.active:
            self.stop_listening()
        else:
            self.start_listening()

    def _refresh_state(self):
        self._draw_button()
        self.idle_status()
        self.heard_lbl.config(text="")
        if self.tray is not None:
            try:
                self.tray.icon = system.make_icon(self.listener is not None and self.listener.active)
                self.tray.update_menu()
            except Exception:
                pass

    # Appelé depuis le fil d'écoute à chaque phrase reconnue
    def on_heard(self, text):
        self.ui(self.heard_lbl.config, {"text": f"Entendu : « {text} »"})
        n = normalize(text)
        if self.speaker and self.speaker.speaking:
            # Pendant que Celia parle, on n'écoute que les ordres d'arrêt.
            rest = find_wake_word(text, self.name, self.cfg.get("wake_sensitivity", 0.78))
            if rest is not None and normalize(rest) in STOP_WORDS | {""}:
                self.ui(self.interrupt)
            return
        if self.busy:
            return
        if time.time() < self.awaiting_until:
            self.awaiting_until = 0
            self.ui(self.handle_question, text)
            return
        rest = find_wake_word(text, self.name, self.cfg.get("wake_sensitivity", 0.78))
        if rest is None:
            return
        beep()
        if len(rest.split()) == 0:
            self.ui(self.set_status, "Oui ? Je vous écoute…")
            self.speaker.say("Oui ?")
            self.awaiting_until = time.time() + FOLLOW_UP_SECONDS + 1
        else:
            self.ui(self.handle_question, rest)

    def handle_question(self, question):
        nq = normalize(question)
        if nq in STOP_WORDS:
            self.interrupt()
            return
        if SLEEP_RE.search(nq):
            self.add_log("you", question)
            self.speak("D'accord, je me mets en veille. Cliquez sur mon bouton pour me réveiller.",
                       after=self.stop_listening)
            return
        if RESET_RE.search(nq):
            self.add_log("you", question)
            self.brain.reset()
            self.speak("C'est noté, on repart de zéro.")
            return

        self.add_log("you", question)
        self.busy = True
        self.set_status("Je réfléchis…")

        def work():
            answer = self.brain.ask(question)
            self.ui(self._answer_ready, answer)
        threading.Thread(target=work, daemon=True).start()

    def _answer_ready(self, answer):
        self.busy = False
        self.speak(answer)

    def speak(self, text, after=None):
        self.add_log("celia", text)
        self.set_status("Je parle… (dites « " + self.name + " stop » ou cliquez sur Interrompre)")

        def done():
            self.ui(self.idle_status)
            if after:
                self.ui(after)
        if self.speaker:
            self.speaker.say(text, on_done=done)
        else:
            done()

    def interrupt(self):
        if self.speaker:
            self.speaker.interrupt()
        self.idle_status()

    def new_conversation(self):
        self.brain.reset()
        self.add_log("info", "— Nouvelle conversation —")

    def _send_typed(self):
        text = self.entry.get().strip()
        if text and not self.busy:
            self.entry.delete(0, "end")
            self.handle_question(text)

    # ------------------------------------------------------------------ #
    #  Réglages
    # ------------------------------------------------------------------ #
    def open_settings(self, first_run=False):
        win = tk.Toplevel(self.root)
        win.title("Réglages")
        win.configure(bg=BG, padx=16, pady=12)
        win.transient(self.root)
        win.resizable(False, False)
        r = 0

        def label(text, hint=None):
            nonlocal r
            tk.Label(win, text=text, bg=BG, fg=FG, font=(FONT, 10, "bold")).grid(
                row=r, column=0, sticky="w", pady=(8, 0))
            r += 1
            if hint:
                tk.Label(win, text=hint, bg=BG, fg=MUTED, font=(FONT, 8), wraplength=360,
                         justify="left").grid(row=r, column=0, sticky="w")
                r += 1

        def place(widget):
            nonlocal r
            widget.grid(row=r, column=0, sticky="we", pady=2)
            r += 1

        if first_run:
            tk.Label(win, text="Bienvenue ! Pour que je puisse répondre, collez votre clé API\n"
                               "Anthropic (console.anthropic.com → API Keys).",
                     bg=BG, fg=ACCENT, font=(FONT, 10), justify="left").grid(row=r, column=0, sticky="w")
            r += 1

        v_name = tk.StringVar(value=self.cfg["assistant_name"])
        label("Prénom de l'assistante", "C'est le mot que vous direz pour l'appeler.")
        place(tk.Entry(win, textvariable=v_name, width=44))

        v_user = tk.StringVar(value=self.cfg["user_name"])
        label("Votre prénom (facultatif)")
        place(tk.Entry(win, textvariable=v_user, width=44))

        v_key = tk.StringVar(value=self.cfg["api_key"])
        label("Clé API Anthropic", "Stockée uniquement sur cet ordinateur.")
        key_entry = tk.Entry(win, textvariable=v_key, width=44, show="•")
        place(key_entry)

        v_model = tk.StringVar(value=MODELS.get(self.cfg["model"], list(MODELS.values())[0]))
        label("Modèle Claude")
        place(ttk.Combobox(win, textvariable=v_model, values=list(MODELS.values()), state="readonly", width=42))

        v_effort = tk.StringVar(value=self.cfg["effort"])
        label("Profondeur de réflexion", "low = réponse rapide (conseillé à l'oral), high = plus approfondi.")
        place(ttk.Combobox(win, textvariable=v_effort, values=EFFORTS, state="readonly", width=42))

        v_web = tk.BooleanVar(value=self.cfg["web_search"])
        place(tk.Checkbutton(win, text="Recherche web (actualité, météo…)", variable=v_web, bg=BG, fg=FG,
                             selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                             highlightthickness=0, bd=0, anchor="w"))

        voices = self.speaker.voices if self.speaker else []
        names = ["(automatique — voix française)"] + [n for _, n in voices]
        current = next((n for i, n in voices if i == self.cfg["voice_id"]), names[0])
        v_voice = tk.StringVar(value=current)
        label("Voix")
        place(ttk.Combobox(win, textvariable=v_voice, values=names, state="readonly", width=42))

        v_rate = tk.IntVar(value=self.cfg["speech_rate"])
        label("Vitesse de parole")
        place(tk.Scale(win, from_=120, to=260, orient="horizontal", variable=v_rate, bg=BG, fg=FG,
                       highlightthickness=0, troughcolor=PANEL))

        v_sens = tk.DoubleVar(value=self.cfg["wake_sensitivity"])
        label("Exigence de reconnaissance du prénom",
              "Plus bas = réagit plus facilement (mais plus de faux déclenchements).")
        place(tk.Scale(win, from_=0.6, to=0.95, resolution=0.01, orient="horizontal", variable=v_sens,
                       bg=BG, fg=FG, highlightthickness=0, troughcolor=PANEL))

        v_auto = tk.BooleanVar(value=self.cfg["start_with_system"])
        place(tk.Checkbutton(win, text=f"Lancer {self.name} automatiquement à l'ouverture de session",
                             variable=v_auto, bg=BG, fg=FG, selectcolor=PANEL,
                             activebackground=BG, activeforeground=FG,
                             highlightthickness=0, bd=0, anchor="w"))

        v_brief = tk.BooleanVar(value=self.cfg["morning_briefing"])
        place(tk.Checkbutton(win, text="Point du jour à voix haute au premier lancement de la journée",
                             variable=v_brief, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG,
                             activeforeground=FG, highlightthickness=0, bd=0, anchor="w"))

        v_remind = tk.BooleanVar(value=self.cfg["reminders"])
        place(tk.Checkbutton(win, text="Rappels vocaux à l'heure prévue des tâches",
                             variable=v_remind, bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG,
                             activeforeground=FG, highlightthickness=0, bd=0, anchor="w"))

        v_pdir = tk.StringVar(value=self.cfg["projects_dir"])
        label("Dossier des projets", f"{self.name} y crée un sous-dossier pour chaque nouveau projet.")
        place(tk.Entry(win, textvariable=v_pdir, width=44))

        v_listen = tk.BooleanVar(value=self.cfg["listen_on_start"])
        place(tk.Checkbutton(win, text="Écoute active dès le lancement", variable=v_listen, bg=BG, fg=FG,
                             selectcolor=PANEL, activebackground=BG, activeforeground=FG,
                             highlightthickness=0, bd=0, anchor="w"))

        def save():
            name = v_name.get().strip()
            if not name:
                messagebox.showwarning("Réglages", "Le prénom ne peut pas être vide.", parent=win)
                return
            self.cfg["assistant_name"] = name
            self.cfg["user_name"] = v_user.get().strip()
            self.cfg["api_key"] = v_key.get().strip()
            self.cfg["model"] = next((k for k, v in MODELS.items() if v == v_model.get()), "claude-opus-5-5")
            self.cfg["effort"] = v_effort.get()
            self.cfg["web_search"] = v_web.get()
            self.cfg["voice_id"] = next((i for i, n in voices if n == v_voice.get()), "")
            self.cfg["speech_rate"] = int(v_rate.get())
            self.cfg["wake_sensitivity"] = round(float(v_sens.get()), 2)
            self.cfg["listen_on_start"] = v_listen.get()
            self.cfg["morning_briefing"] = v_brief.get()
            self.cfg["reminders"] = v_remind.get()
            self.cfg["projects_dir"] = v_pdir.get().strip() or self.cfg["projects_dir"]
            if v_auto.get() != self.cfg["start_with_system"]:
                try:
                    system.set_autostart(v_auto.get())
                    self.cfg["start_with_system"] = v_auto.get()
                except Exception as e:
                    messagebox.showerror("Démarrage automatique", str(e), parent=win)
            self.cfg.save()
            if self.speaker:
                self.speaker.configure(self.cfg["voice_id"], self.cfg["speech_rate"])
            self.title_lbl.config(text=self.name)
            self.root.title(self.name)
            self.idle_status()
            if self.tray is not None:
                self.tray.title = self.name
            win.destroy()

        btns = tk.Frame(win, bg=BG)
        btns.grid(row=r, column=0, sticky="e", pady=(14, 0))
        self._btn(btns, "Annuler", win.destroy).pack(side="left", padx=6)
        tk.Button(btns, text="Enregistrer", command=save, bg=ACCENT, fg="white", relief="flat",
                  font=(FONT, 9, "bold"), padx=14, pady=5).pack(side="left")
        win.grab_set()

    # ------------------------------------------------------------------ #
    #  Zone de notification (icône près de l'horloge)
    # ------------------------------------------------------------------ #
    def _start_tray(self):
        if IS_MAC:
            return  # sur Mac, Celia vit dans le Dock (pystray et Tk ne peuvent pas cohabiter)
        try:
            import pystray
        except Exception:
            return
        active = lambda item: self.listener is not None and self.listener.active
        menu = pystray.Menu(
            pystray.MenuItem("Ouvrir", lambda: self.ui(self.show_window), default=True),
            pystray.MenuItem("Écoute active", lambda: self.ui(self.toggle), checked=active),
            pystray.MenuItem("Quitter", lambda: self.ui(self.quit)),
        )
        try:
            self.tray = pystray.Icon("Celia", system.make_icon(True), self.name, menu)
            self.tray.run_detached()
        except Exception as e:
            print("Icône de notification indisponible :", e)
            self.tray = None

    def hide_window(self):
        if self.tray is not None:
            self.root.withdraw()  # Celia continue de tourner en arrière-plan
            if not getattr(self, "_hint_shown", False):
                self._hint_shown = True
                try:
                    self.tray.notify("Je reste active en arrière-plan. "
                                     "Clic droit sur mon icône pour me quitter.", self.name)
                except Exception:
                    pass
        elif IS_MAC:
            self.root.withdraw()  # comme les apps Mac : la fenêtre se ferme, Celia reste dans le Dock
        else:
            self.root.iconify()

    def notify(self, title, message):
        """Notification système (centre de notifications sur Mac, bulle sur Windows)."""
        try:
            if IS_MAC:
                import subprocess
                subprocess.Popen(["osascript", "-e", "on run argv", "-e",
                                  "display notification (item 2 of argv) with title (item 1 of argv)",
                                  "-e", "end run", title, message])
            elif self.tray is not None:
                self.tray.notify(message, title)
        except Exception:
            pass

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ------------------------------------------------------------------ #
    #  Briefing du matin et rappels
    # ------------------------------------------------------------------ #
    def _morning_briefing(self):
        if self.speaker is None:
            self.root.after(1000, self._morning_briefing)
            return
        today = time.strftime("%Y-%m-%d")
        if not self.cfg.get("morning_briefing", True) or self.memory.data.get("last_briefing") == today:
            return
        with self.memory.lock:
            self.memory.data["last_briefing"] = today
            self.memory._save()
        self.speak(self.memory.briefing(self.cfg.get("user_name", "")))

    def _check_reminders(self):
        try:
            if self.cfg.get("reminders", True):
                for t in self.memory.due_reminders():
                    text = f"Petit rappel : {t['title']}."
                    if t.get("project"):
                        text += f" C'est pour le projet {t['project']}."
                    self.notify(f"{self.name} — rappel", t["title"])
                    self.speak(text)
        finally:
            self.root.after(20000, self._check_reminders)

    # ------------------------------------------------------------------ #
    #  Fenêtre « Planning & mémoire »
    # ------------------------------------------------------------------ #
    def open_planning(self):
        if self.planning_win is not None and self.planning_win.winfo_exists():
            self.planning_win.deiconify()
            self.planning_win.lift()
            return
        win = self.planning_win = tk.Toplevel(self.root)
        win.title(f"{self.name} — Planning & mémoire")
        win.geometry("720x480")
        win.configure(bg=BG)
        style = ttk.Style(win)
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=24,
                        borderwidth=0)
        style.configure("Treeview.Heading", background=BG, foreground=FG, relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=FG, padding=(12, 4))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", "white")])

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        def tab(title, columns, widths):
            frame = tk.Frame(nb, bg=BG)
            nb.add(frame, text=title)
            tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
            for c, w in zip(columns, widths):
                tree.heading(c, text=c)
                tree.column(c, width=w, anchor="w", stretch=(w > 200))
            sb = tk.Scrollbar(frame, command=tree.yview)
            tree.configure(yscrollcommand=sb.set)
            bar = tk.Frame(frame, bg=BG)
            bar.pack(side="bottom", fill="x", pady=6)
            sb.pack(side="right", fill="y")
            tree.pack(fill="both", expand=True)
            return tree, bar

        # Onglet tâches
        self.pl_tasks, bar = tab("Planning", ("Quand", "Tâche", "Projet"), (170, 380, 140))
        self.pl_show_done = tk.BooleanVar(value=False)
        self._btn(bar, "✔ Terminée", lambda: self._task_action("done")).pack(side="left")
        self._btn(bar, "🗑 Supprimer", lambda: self._task_action("delete")).pack(side="left", padx=6)
        tk.Checkbutton(bar, text="Afficher les tâches terminées", variable=self.pl_show_done,
                       command=self._refresh_planning, bg=BG, fg=FG, selectcolor=PANEL,
                       activebackground=BG, activeforeground=FG, highlightthickness=0, bd=0).pack(side="left", padx=6)
        add = tk.Frame(self.pl_tasks.master, bg=BG)
        add.pack(side="bottom", fill="x", before=bar)
        self.pl_new = tk.Entry(add, bg=PANEL, fg=FG, insertbackground=FG, relief="flat")
        self.pl_new.pack(side="left", fill="x", expand=True, ipady=4)
        self.pl_new_date = tk.Entry(add, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=12)
        self.pl_new_date.insert(0, time.strftime("%Y-%m-%d"))
        self.pl_new_date.pack(side="left", padx=4, ipady=4)
        self.pl_new_time = tk.Entry(add, bg=PANEL, fg=FG, insertbackground=FG, relief="flat", width=6)
        self.pl_new_time.pack(side="left", ipady=4)
        self._btn(add, "+ Ajouter", self._add_task_manual).pack(side="left", padx=(4, 0))
        tk.Label(self.pl_tasks.master, text="Nouvelle tâche  ·  date (AAAA-MM-JJ, vide = sans date)  ·  heure (HH:MM)",
                 bg=BG, fg=MUTED, font=(FONT, 8)).pack(side="bottom", anchor="w", before=add)

        # Onglet mémoire
        self.pl_notes, bar = tab("Mémoire", ("Date", "Type", "Projet", "Contenu"), (120, 150, 120, 320))
        self._btn(bar, "🗑 Oublier", self._delete_note).pack(side="left")

        # Onglet projets
        self.pl_projects, bar = tab("Projets", ("Projet", "Statut", "Créé", "Dossier"), (180, 90, 110, 320))
        self._btn(bar, "📂 Ouvrir le dossier", self._open_project_folder).pack(side="left")

        self._refresh_planning()

    def _refresh_planning(self):
        if self.planning_win is None or not self.planning_win.winfo_exists():
            return
        m = self.memory
        tree = self.pl_tasks
        tree.delete(*tree.get_children())
        for t in m.list_tasks(include_done=self.pl_show_done.get()):
            when = fr_date(t["date"]) if t["date"] else "sans date"
            if t["time"]:
                when += f" · {t['time']}"
            title = ("✔ " if t["done"] else "") + t["title"]
            tree.insert("", "end", iid=t["id"], values=(when, title, t.get("project") or ""))
        tree = self.pl_notes
        tree.delete(*tree.get_children())
        for n in reversed(m.data["notes"]):
            tree.insert("", "end", iid=n["id"], values=(fr_date(n["date"][:10]), NOTE_KINDS.get(n["kind"], "Note"),
                                                       n.get("project") or "", n["text"]))
        tree = self.pl_projects
        tree.delete(*tree.get_children())
        for p in reversed(m.data["projects"]):
            tree.insert("", "end", iid=p["id"], values=(p["name"], p["status"], fr_date(p["created"][:10]),
                                                       p["folder"]))

    def _task_action(self, action):
        sel = self.pl_tasks.selection()
        if not sel:
            return
        if action == "done":
            t = self.memory.find_task(sel[0])
            self.memory.update_task(sel[0], done=not t["done"])
        elif messagebox.askyesno("Supprimer", "Supprimer cette tâche ?", parent=self.planning_win):
            self.memory.delete_task(sel[0])

    def _add_task_manual(self):
        title = self.pl_new.get().strip()
        if not title:
            return
        try:
            self.memory.add_task(title, self.pl_new_date.get().strip() or None, self.pl_new_time.get().strip() or None)
        except ValueError as e:
            messagebox.showwarning("Planning", str(e), parent=self.planning_win)
            return
        self.pl_new.delete(0, "end")
        self.pl_new_time.delete(0, "end")

    def _delete_note(self):
        sel = self.pl_notes.selection()
        if sel and messagebox.askyesno("Oublier", "Effacer ce souvenir ?", parent=self.planning_win):
            self.memory.delete_note(sel[0])

    def _open_project_folder(self):
        sel = self.pl_projects.selection()
        if not sel:
            return
        folder = next((p["folder"] for p in self.memory.data["projects"] if p["id"] == sel[0]), None)
        if not folder:
            return
        import subprocess
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as e:
            messagebox.showerror("Dossier", str(e), parent=self.planning_win)

    def handle_command(self, cmd):  # depuis les raccourcis du bureau
        if cmd == "show":
            self.ui(self.show_window)
        elif cmd == "toggle":
            self.ui(self.toggle)
        elif cmd == "quit":
            self.ui(self.quit)

    def quit(self):
        try:
            if self.listener:
                self.listener.stop()
            if self.tray is not None:
                self.tray.stop()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if "--install-shortcuts" in argv:
        for p in system.install_shortcuts():
            print("Raccourci créé :", p)
        return
    command = "toggle" if "--toggle" in argv else "quit" if "--quit" in argv else "show"
    if system.send_to_running_instance(command):
        return  # Celia tourne déjà : on lui a transmis la commande
    if command == "quit":
        return
    app = CeliaApp(start_toggled_off=False)
    try:
        app._server = system.serve_commands(app.handle_command)
    except OSError:
        pass
    app.run()
    os._exit(0)  # termine aussi le fil de l'icône de notification
