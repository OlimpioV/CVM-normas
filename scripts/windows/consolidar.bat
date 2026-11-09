@echo off
rem Repositorio Normativo CVM: gera a versao consolidada (so o texto vigente) das normas alteradas
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm consolidar %*
pause
