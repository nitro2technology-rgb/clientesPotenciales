"""
Punto de entrada para Vercel.

Vercel busca las funciones dentro de api/ y, si el modulo expone una variable
`app` que sea una aplicacion ASGI, la sirve directamente. Aqui no hay logica:
solo se importa la app de FastAPI de siempre.

En local esto no se usa: sigue mandando `python run.py`.
"""
import sys
from pathlib import Path

# La raiz del proyecto no esta garantizada en sys.path dentro de la funcion,
# y sin ella `from app.main import ...` no resuelve.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.main import app  # noqa: E402  (tiene que ir despues del sys.path)

__all__ = ["app"]
