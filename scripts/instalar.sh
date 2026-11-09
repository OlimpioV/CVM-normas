#!/bin/sh
# Instala o ambiente virtual, as dependências fixadas e o modelo de OCR em português (Linux e macOS).
# Uso, na raiz do projeto: sh scripts/instalar.sh
set -e
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
if [ ! -f ferramentas/tessdata/por.traineddata ]; then
  mkdir -p ferramentas/tessdata
  curl -L --fail -o ferramentas/tessdata/por.traineddata \
    https://github.com/tesseract-ocr/tessdata_best/raw/main/por.traineddata
fi
echo "Pronto. Exemplo: .venv/bin/repositorio-cvm --help"
