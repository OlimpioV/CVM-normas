@echo off
rem Repositorio Normativo CVM: coleta historica dos atos do catalogo oficial ausentes do acervo (retomavel)
rem Exemplos: coletar-catalogo.bat --familia resolucao    coletar-catalogo.bat --amostra 20
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm coletar-catalogo %*
pause
