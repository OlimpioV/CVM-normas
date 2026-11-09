@echo off
rem Repositorio Normativo CVM: le o catalogo oficial completo da CVM (base do relatorio de cobertura)
rem Le so a listagem (titulo, data, endereco), nao baixa as normas. Leva cerca de 15 minutos.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm ler-catalogo %*
