"""
Punto de entrada para Vercel.

Vercel busca las funciones dentro de api/ y, si el modulo expone una variable
`app` que sea una aplicacion ASGI, la sirve directamente.

Por que hay un envoltorio y no un simple import
-----------------------------------------------
En vercel.json todas las rutas se redirigen a esta funcion. Al hacerlo, Vercel
reescribe la ruta: la app recibe `/api/index/lo-que-fuera` en vez de
`/lo-que-fuera`, y FastAPI responde 404 a todo porque ninguna de sus rutas
empieza por ahi.

Asi que aqui se le devuelve la ruta original antes de pasarsela. Si algun dia
Vercel dejara de reescribir y mandara ya la ruta buena, este envoltorio no hace
nada: solo actua cuando el prefijo esta presente.

En local esto no se usa: sigue mandando `python run.py`.
"""
import sys
from pathlib import Path

# La raiz del proyecto no esta garantizada en sys.path dentro de la funcion,
# y sin ella `from app.main import ...` no resuelve.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.main import app as app_fastapi  # noqa: E402  (va tras el sys.path)

PREFIJO = "/api/index"


def _ruta_original(ruta: str) -> str:
    """Quita el prefijo que mete la reescritura de Vercel."""
    if ruta == PREFIJO:
        return "/"
    if ruta.startswith(PREFIJO + "/"):
        return ruta[len(PREFIJO):]
    return ruta


async def app(scope, receive, send):
    if scope["type"] in ("http", "websocket"):
        ruta = scope.get("path", "")
        limpia = _ruta_original(ruta)
        if limpia != ruta:
            scope = dict(scope, path=limpia, raw_path=limpia.encode("utf-8"))
    await app_fastapi(scope, receive, send)
