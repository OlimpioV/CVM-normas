@echo off
rem Repositorio Normativo CVM: abre a interface de pesquisa no navegador (http://127.0.0.1:8000)
rem Para encerrar, feche esta janela.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm interface %*
