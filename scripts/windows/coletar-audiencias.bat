@echo off
rem Repositorio Normativo CVM: audiencias publicas das normas do acervo (edital, prazo, fase, relatorio)
rem Nao baixa as manifestacoes recebidas. Retomavel: o que ja foi baixado nao e baixado de novo.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm coletar-audiencias %*
