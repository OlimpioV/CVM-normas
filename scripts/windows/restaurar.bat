@echo off
rem Repositorio Normativo CVM: restaura o banco a partir de uma copia em dados\backups
rem Sem argumentos lista as copias. Exemplo: restaurar.bat acervo-20261028-101500-manual.sqlite --confirmar
rem O banco atual e copiado antes da restauracao.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm restaurar %*
