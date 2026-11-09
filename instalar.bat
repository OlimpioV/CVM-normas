@echo off
rem Instala o ambiente virtual, as dependencias fixadas e o modelo de OCR em portugues
cd /d "%~dp0"
py -3 -m venv .venv
".venv\Scripts\python.exe" -m pip install -r requirements.txt
".venv\Scripts\python.exe" -m pip install -e .
if not exist "ferramentas\tessdata\por.traineddata" (
  mkdir "ferramentas\tessdata" 2>nul
  curl -L --fail -o "ferramentas\tessdata\por.traineddata" https://github.com/tesseract-ocr/tessdata_best/raw/main/por.traineddata
)
pause
