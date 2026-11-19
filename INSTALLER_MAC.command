#!/bin/bash
# Installation de Celia sur Mac : double-cliquez sur ce fichier.
# (Si macOS le bloque : clic droit > Ouvrir, puis « Ouvrir ».)
cd "$(dirname "$0")" || exit 1
echo ""
echo "  ===  Installation de Celia, votre assistante vocale  ==="
echo ""

# Cherche un Python 3.10+ avec l'interface graphique (Tk). Le Python de python.org est conseillé.
PY=""
for c in /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
         /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && \
     "$c" -c 'import sys, tkinter; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "  Il faut d'abord installer Python (version 3.10 ou plus récente)."
  echo "  La page de téléchargement va s'ouvrir : prenez « macOS 64-bit universal2 installer »,"
  echo "  installez-le, puis relancez ce fichier."
  open "https://www.python.org/downloads/macos/"
  read -r -p "  Appuyez sur Entrée pour fermer…" _
  exit 1
fi
echo "  Python utilisé : $("$PY" --version)"

echo "  [1/3] Création de l'environnement…"
[ -d .venv ] || "$PY" -m venv .venv || { echo "Échec."; exit 1; }
echo "  [2/3] Installation des composants (quelques minutes)…"
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt -q || { echo "Échec de l'installation."; read -r _; exit 1; }
echo "  [3/3] Création des applications Celia (Bureau + Applications)…"
.venv/bin/python -m celia --install-shortcuts || { echo "Échec."; read -r _; exit 1; }

echo ""
echo "  Installation terminée !"
echo "   - « Celia »        : ouvre l'assistante (à lancer le matin)"
echo "   - « Celia ON-OFF » : active / coupe l'écoute"
echo "  Au premier lancement, macOS vous demandera l'accès au micro : cliquez sur « Autoriser »."
echo ""
open "$HOME/Applications/Celia.app"
read -r -p "  Appuyez sur Entrée pour fermer cette fenêtre…" _
