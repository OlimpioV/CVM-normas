@echo off
rem Repositorio Normativo CVM: relatorio-gabarito
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm relatorio-gabarito %*
pause
