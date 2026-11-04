@echo off
REM Opens the offline register: starts a small local web server with Windows PowerShell.
cd /d "%~dp0"
if not exist "outils\serveur.ps1" goto :notextracted
if not exist "site\index.html" goto :notextracted
powershell -NoProfile -ExecutionPolicy Bypass -File "outils\serveur.ps1" -Root "site"
if not "%errorlevel%"=="0" pause
exit /b
:notextracted
echo.
echo Le registre ne peut pas demarrer depuis l'apercu du fichier .zip.
echo Fermez cette fenetre, faites un clic droit sur l'archive .zip,
echo choisissez "Extraire tout...", puis ouvrez le dossier extrait
echo et double-cliquez a nouveau sur "Ouvrir le registre (Windows)".
echo.
pause
exit /b 1
