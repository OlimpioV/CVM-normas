@echo off
rem Repositorio Normativo CVM: atualizacao incremental (novidades e alteracoes nas fontes oficiais)
rem Use --arquivos para baixar de novo tambem os arquivos de texto. Log em dados\logs, relatorio em dados\relatorios.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm atualizar %*
