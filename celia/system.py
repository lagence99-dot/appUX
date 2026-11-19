"""Intégration au système : icône, raccourcis du bureau, lancement au démarrage, instance unique."""
import os
import socket
import subprocess
import sys
import threading
from pathlib import Path

from .config import app_dir

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "Celia.pyw"
PORT = 52817  # port local (127.0.0.1) pour piloter l'instance déjà lancée


# --------------------------------------------------------------------------- #
#  Icône
# --------------------------------------------------------------------------- #
def make_icon(active: bool = True, size: int = 64):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (124, 92, 255) if active else (110, 110, 120)
    d.ellipse((2, 2, size - 2, size - 2), fill=color)
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.55))
    except OSError:
        font = ImageFont.load_default()
    d.text((size / 2, size / 2), "C", fill="white", font=font, anchor="mm")
    return img


def icon_file() -> Path:
    path = app_dir() / "celia.ico"
    if not path.exists():
        make_icon(True, 256).save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    return path


# --------------------------------------------------------------------------- #
#  Python sans console
# --------------------------------------------------------------------------- #
def gui_python() -> str:
    exe = Path(sys.executable)
    if sys.platform == "win32" and exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


# --------------------------------------------------------------------------- #
#  Raccourcis du bureau
# --------------------------------------------------------------------------- #
def desktop_dir() -> Path:
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                capture_output=True, text=True, timeout=15).stdout.strip()
            if out:
                return Path(out)
        except Exception:
            pass
    return Path.home() / "Desktop"


def _win_shortcut(lnk: Path, target: str, args: str, icon: Path, description: str):
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
        "$s.TargetPath=$env:TGT;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:WD;"
        "$s.IconLocation=$env:ICO;$s.Description=$env:DESC;$s.Save()"
    )
    env = dict(os.environ, LNK=str(lnk), TGT=target, ARGS=args, WD=str(ROOT),
               ICO=str(icon), DESC=description)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True, timeout=30)


def install_shortcuts() -> list:
    desk = desktop_dir()
    desk.mkdir(parents=True, exist_ok=True)
    created = []
    items = [("Celia", "", "Ouvrir l'assistante vocale Celia"),
             ("Celia ON-OFF", "--toggle", "Activer / désactiver l'écoute de Celia")]
    if sys.platform == "win32":
        ico = icon_file()
        for name, args, desc in items:
            lnk = desk / f"{name}.lnk"
            _win_shortcut(lnk, gui_python(), f'"{LAUNCHER}" {args}'.strip(), ico, desc)
            created.append(lnk)
    elif sys.platform == "darwin":
        for name, args, _ in items:
            f = desk / f"{name}.command"
            f.write_text(f'#!/bin/sh\n"{sys.executable}" "{LAUNCHER}" {args} >/dev/null 2>&1 &\n')
            f.chmod(0o755)
            created.append(f)
    else:
        ico = app_dir() / "celia.png"
        make_icon(True, 128).save(ico)
        for name, args, desc in items:
            f = desk / f"{name.replace(' ', '-')}.desktop"
            f.write_text("[Desktop Entry]\nType=Application\n"
                         f"Name={name}\nComment={desc}\n"
                         f'Exec="{sys.executable}" "{LAUNCHER}" {args}\nIcon={ico}\nTerminal=false\n')
            f.chmod(0o755)
            created.append(f)
    return created


# --------------------------------------------------------------------------- #
#  Lancement au démarrage de la session
# --------------------------------------------------------------------------- #
def set_autostart(enabled: bool):
    if sys.platform == "win32":
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        with key:
            if enabled:
                winreg.SetValueEx(key, "Celia", 0, winreg.REG_SZ, f'"{gui_python()}" "{LAUNCHER}"')
            else:
                try:
                    winreg.DeleteValue(key, "Celia")
                except FileNotFoundError:
                    pass
    elif sys.platform == "darwin":
        plist = Path.home() / "Library" / "LaunchAgents" / "com.celia.assistant.plist"
        if enabled:
            plist.parent.mkdir(parents=True, exist_ok=True)
            plist.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                "<key>Label</key><string>com.celia.assistant</string>"
                f"<key>ProgramArguments</key><array><string>{sys.executable}</string>"
                f"<string>{LAUNCHER}</string></array>"
                "<key>RunAtLoad</key><true/></dict></plist>\n")
        else:
            plist.unlink(missing_ok=True)
    else:
        f = Path.home() / ".config" / "autostart" / "celia.desktop"
        if enabled:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("[Desktop Entry]\nType=Application\nName=Celia\n"
                         f'Exec="{sys.executable}" "{LAUNCHER}"\n')
        else:
            f.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
#  Instance unique
# --------------------------------------------------------------------------- #
def send_to_running_instance(command: str) -> bool:
    """Si Celia tourne déjà, lui envoie la commande et retourne True."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1) as s:
            s.sendall(command.encode())
        return True
    except OSError:
        return False


def serve_commands(handler):
    """Écoute les commandes des raccourcis (« show », « toggle »)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(5)

    def loop():
        while True:
            conn, _ = srv.accept()
            with conn:
                try:
                    cmd = conn.recv(64).decode(errors="ignore").strip()
                except OSError:
                    continue
                if cmd in ("show", "toggle", "quit"):
                    handler(cmd)
    threading.Thread(target=loop, daemon=True).start()
    return srv
