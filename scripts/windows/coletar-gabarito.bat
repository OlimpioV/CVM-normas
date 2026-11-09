@echo off
rem Repositorio Normativo CVM: coletar-gabarito
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm coletar --gabarito %*
pause
