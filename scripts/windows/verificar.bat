@echo off
rem Repositorio Normativo CVM: verificar
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm verificar %*
pause
