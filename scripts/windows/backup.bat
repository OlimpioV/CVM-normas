@echo off
rem Repositorio Normativo CVM: backup
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm backup %*
pause
