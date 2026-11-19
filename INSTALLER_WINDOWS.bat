@echo off
chcp 65001 >nul
title Installation de Celia
cd /d "%~dp0"
echo.
echo  ===  Installation de Celia, votre assistante vocale  ===
echo.
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo  Python n'est pas installe.
  echo  Installez-le depuis https://www.python.org/downloads/ en cochant
  echo  "Add python.exe to PATH", puis relancez ce fichier.
  pause
  exit /b 1
)
echo  [1/3] Creation de l'environnement...
if not exist .venv %PY% -m venv .venv || goto :error
echo  [2/3] Installation des composants (quelques minutes)...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt -q || goto :error
echo  [3/3] Creation des raccourcis sur le bureau...
.venv\Scripts\python.exe -m celia --install-shortcuts || goto :error
echo.
echo  Installation terminee !
echo  - "Celia"        : ouvre l'assistante (a lancer le matin)
echo  - "Celia ON-OFF" : active / coupe l'ecoute d'un double-clic
echo.
start "" .venv\Scripts\pythonw.exe Celia.pyw
pause
exit /b 0
:error
echo.
echo  Une erreur est survenue pendant l'installation.
pause
exit /b 1
