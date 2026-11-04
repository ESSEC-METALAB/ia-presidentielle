@echo off
REM Opens the offline register: starts a small local web server with Windows PowerShell.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "outils\serveur.ps1" -Root "site"
if errorlevel 1 pause
