@echo off
rem Repositorio Normativo CVM: exporta uma norma. Exemplo: exportar.bat resolucao-cvm-175 docx
rem Formatos: docx, pdf, md, txt. Use --versao original para a redacao original.
cd /d "%~dp0..\.."
".venv\Scripts\python.exe" -m repositorio_cvm exportar %* --saida exportados
