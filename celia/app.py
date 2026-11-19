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
from .voice import Speaker, beep, ensure_vosk_model, find_wake_word, normalize

FOLLOW_UP_SECONDS = 8   # après « Oui ? », délai pour poser la question

STOP_WORDS = {"stop", "arrete", "arrete toi", "tais toi", "silence", "chut", "ca suffit"}
SLEEP_RE = re.compile(r"\b(mets toi en (veille|pause)|desactive toi|va dormir)\b")
RESET_RE = re.compile(r"\b(nouvelle conversation|oublie tout|on recommence)\b")

BG, PANEL, FG, MUTED = "#15151c", "#20202a", "#ececf1", "#9a9aab"
ON, OFF, ACCENT = "#2ecc71", "#5a5a66", "#7c5cff"


class CeliaApp:
    def __init__(self, start_toggled_off=False):
        self.cfg = Config()
        self.brain = Brain(self.cfg)
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
        self._build_ui()
        self.root.after(100, self._pump)

        threading.Thread(target=self._init_voice, daemon=True).start()
        self._start_tray()
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

        self.title_lbl = tk.Label(self.root, text=self.name, font=("Segoe UI", 26, "bold"),
                                  bg=BG, fg=FG)
        self.title_lbl.pack(pady=(18, 0))

        self.canvas = tk.Canvas(self.root, width=150, height=150, bg=BG, highlightthickness=0,
                                cursor="hand2")
        self.canvas.pack(pady=10)
        self.canvas.bind("<Button-1>", lambda e: self.toggle())
        self._draw_button()

        self.status_lbl = tk.Label(self.root, text="Démarrage…", font=("Segoe UI", 11),
                                   bg=BG, fg=MUTED, wraplength=400)
        self.status_lbl.pack()
        self.heard_lbl = tk.Label(self.root, text="", font=("Segoe UI", 9, "italic"),
                                  bg=BG, fg=MUTED, wraplength=400)
        self.heard_lbl.pack(pady=(2, 8))

        frame = tk.Frame(self.root, bg=BG)
        frame.pack(fill="both", expand=True, padx=14)
        self.log = tk.Text(frame, bg=PANEL, fg=FG, relief="flat", wrap="word",
                           font=("Segoe UI", 10), padx=10, pady=8, state="disabled")
        sb = tk.Scrollbar(frame, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_configure("you", foreground="#8fd3ff", font=("Segoe UI", 10, "bold"))
        self.log.tag_configure("celia", foreground="#c9b8ff", font=("Segoe UI", 10, "bold"))
        self.log.tag_configure("info", foreground=MUTED, font=("Segoe UI", 9, "italic"))

        entry_row = tk.Frame(self.root, bg=BG)
        entry_row.pack(fill="x", padx=14, pady=8)
        self.entry = tk.Entry(entry_row, bg=PANEL, fg=FG, insertbackground=FG, relief="flat",
                              font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self._send_typed())
        self._btn(entry_row, "Envoyer", self._send_typed).pack(side="left", padx=(6, 0))

        row = tk.Frame(self.root, bg=BG)
        row.pack(fill="x", padx=14, pady=(0, 14))
        self._btn(row, "⏹ Interrompre", self.interrupt).pack(side="left")
        self._btn(row, "↺ Nouvelle conversation", self.new_conversation).pack(side="left", padx=6)
        self._btn(row, "⚙ Réglages", self.open_settings).pack(side="right")

    def _btn(self, parent, text, cmd):
        return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=FG, relief="flat",
                         activebackground=ACCENT, activeforeground="white",
                         font=("Segoe UI", 9), padx=10, pady=5, cursor="hand2")

    def _draw_button(self):
        c = self.canvas
        c.delete("all")
        on = self.listener is not None and self.listener.active
        color = ON if on else OFF
        c.create_oval(8, 8, 142, 142, fill=color, outline="")
        c.create_oval(22, 22, 128, 128, outline="white", width=3)
        c.create_text(75, 66, text="ON" if on else "OFF", fill="white", font=("Segoe UI", 22, "bold"))
        c.create_text(75, 96, text="cliquer pour " + ("couper" if on else "activer"),
                      fill="white", font=("Segoe UI", 8))

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
            tk.Label(win, text=text, bg=BG, fg=FG, font=("Segoe UI", 10, "bold")).grid(
                row=r, column=0, sticky="w", pady=(8, 0))
            r += 1
            if hint:
                tk.Label(win, text=hint, bg=BG, fg=MUTED, font=("Segoe UI", 8), wraplength=360,
                         justify="left").grid(row=r, column=0, sticky="w")
                r += 1

        def place(widget):
            nonlocal r
            widget.grid(row=r, column=0, sticky="we", pady=2)
            r += 1

        if first_run:
            tk.Label(win, text="Bienvenue ! Pour que je puisse répondre, collez votre clé API\n"
                               "Anthropic (console.anthropic.com → API Keys).",
                     bg=BG, fg=ACCENT, font=("Segoe UI", 10), justify="left").grid(row=r, column=0, sticky="w")
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
        place(tk.Checkbutton(win, text="Lancer Celia automatiquement à l'ouverture de session",
                             variable=v_auto, bg=BG, fg=FG, selectcolor=PANEL,
                             activebackground=BG, activeforeground=FG,
                             highlightthickness=0, bd=0, anchor="w"))

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
            if v_auto.get() != self.cfg["start_with_system"]:
                try:
                    system.set_autostart(v_auto.get())
                    self.cfg["start_with_system"] = v_auto.get()
                except Exception as e:
                    messagebox.showerror("Démarrage automatique", str(e), parent=win)
            self.cfg.save()
            if self.speaker:
                self.speaker.configure(self.cfg["voice_id"] or None, self.cfg["speech_rate"])
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
                  font=("Segoe UI", 9, "bold"), padx=14, pady=5).pack(side="left")
        win.grab_set()

    # ------------------------------------------------------------------ #
    #  Zone de notification (icône près de l'horloge)
    # ------------------------------------------------------------------ #
    def _start_tray(self):
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
        else:
            self.root.iconify()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

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
