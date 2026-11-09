@echo off
rem Repositorio Normativo CVM: justificativas de dispensa de Analise de Impacto Regulatorio (AIR) citadas nas fichas
rem Use --refazer para baixar e converter de novo. Log em dados\logs.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm coletar-justificativas %*
