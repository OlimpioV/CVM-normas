@echo off
rem Repositorio Normativo CVM: relatorio de cobertura (dados\relatorios)
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm relatorio-cobertura
