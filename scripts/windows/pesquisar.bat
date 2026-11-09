@echo off
rem Repositorio Normativo CVM: pesquisa. Exemplo: pesquisar.bat Resolucao CVM 50, artigo 1
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm pesquisar %*
