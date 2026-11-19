#!/bin/sh
# Installation de Celia sur Linux (sur Mac, utilisez plutôt INSTALLER_MAC.command)
# Prérequis Debian/Ubuntu : sudo apt install python3-venv python3-tk espeak-ng libportaudio2
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip -q
.venv/bin/python -m pip install -r requirements.txt -q
.venv/bin/python -m celia --install-shortcuts
echo "Installation terminée. Lancement de Celia…"
.venv/bin/python Celia.pyw &
