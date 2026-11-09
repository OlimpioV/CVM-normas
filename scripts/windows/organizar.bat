@echo off
rem Repositorio Normativo CVM: gera dados\biblioteca, com os documentos em pastas de nomes legiveis
rem A pasta e so uma visao dos originais (vinculos, sem ocupar espaco de novo) e pode ser apagada sem perda.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm organizar %*
