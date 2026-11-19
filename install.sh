#!/bin/sh
# Installation de Celia sur macOS / Linux
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
# Linux : il faut aussi « sudo apt install espeak-ng libportaudio2 » (Debian/Ubuntu)
.venv/bin/python -m pip install -r requirements.txt -q
.venv/bin/python -m celia --install-shortcuts
echo "Installation terminée. Lancement de Celia…"
.venv/bin/python Celia.pyw &
