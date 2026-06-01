#!/bin/bash
# Surface — SEO + GEO Optimizer
# Arranca el servidor local y abre la app en el navegador

cd "$(dirname "$0")"

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}▶ Surface — SEO + GEO Optimizer${NC}"
echo ""

# Buscar Python 3.10+ en rutas conocidas de macOS
PYTHON=""
for candidate in \
  /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
  /usr/local/bin/python3.12 /usr/local/bin/python3.11 /usr/local/bin/python3.10 \
  /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10; do
  if [ -x "$candidate" ]; then
    PYTHON=$candidate
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo -e "${RED}✗ Se necesita Python 3.10+. Instálalo con:${NC}"
  echo "  brew install python@3.11"
  echo "  o descarga desde https://python.org"
  exit 1
fi
echo -e "  Python: $($PYTHON --version) → $PYTHON"

# Crear entorno virtual si no existe o está roto
if [ ! -f ".venv/bin/activate" ]; then
  echo -e "${YELLOW}⚙  Creando entorno virtual...${NC}"
  /bin/rm -rf .venv 2>/dev/null || true
  $PYTHON -m venv .venv
  if [ ! -f ".venv/bin/activate" ]; then
    echo -e "${RED}✗ No se pudo crear el entorno virtual.${NC}"
    exit 1
  fi
fi

source .venv/bin/activate

# Instalar dependencias si no están
if ! python -c "import fastapi" 2>/dev/null; then
  echo -e "${YELLOW}⚙  Instalando dependencias (solo la primera vez)...${NC}"
  pip install -r requirements.txt -q
fi

echo -e "${GREEN}✓ Entorno listo${NC}"
echo -e "${GREEN}✓ Abriendo http://localhost:8000/app${NC}"
echo ""
echo "  Pulsa Ctrl+C para detener"
echo ""

(sleep 2 && open "http://localhost:8000/app") &

ENVIRONMENT=dev uvicorn api.index:app --reload --port 8000
