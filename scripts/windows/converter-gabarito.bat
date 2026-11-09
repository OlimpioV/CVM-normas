@echo off
rem Repositorio Normativo CVM: baixa os PDF/DOCX do gabarito e converte em Markdown
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm baixar-arquivos
".venv\Scripts\python.exe" -m repositorio_cvm converter
".venv\Scripts\python.exe" -m repositorio_cvm relatorio-gabarito
pause
