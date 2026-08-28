"""
Cliente minimo de Turso (SQLite alojado) sobre su API HTTP v2.

Por que no el paquete oficial
-----------------------------
`libsql-client` declara `sphinx` y `aiohttp` como dependencias de RUNTIME.
En un despliegue serverless eso son decenas de MB de bundle para nada. La API
HTTP de Turso es un unico POST con JSON, asi que se habla directamente con
`httpx`, que la app ya usaba para Places.

Que expone
----------
Un `conectar()` que imita lo justo de `sqlite3.Connection` que usa storage.py:
execute / executemany / executescript / commit / close, con filas que se
pueden leer por indice (`fila[0]`), por nombre (`fila["lat"]`) y convertir a
dict (`dict(fila)`), igual que `sqlite3.Row`.

Ojo: cada `execute` es un viaje de red y se auto-confirma. No hay
transacciones de varias sentencias; `commit()` existe para no romper la
interfaz pero no hace nada. Para el uso de esta app (un solo usuario,
escrituras pequenas) es suficiente, y `executemany` si viaja en un solo lote.
"""
import base64
from typing import Any, Iterator, Sequence

import httpx

TIMEOUT = 30.0


class ErrorTurso(Exception):
    """Fallo hablando con la base de datos remota."""


# ------------------------------------------------------- (de)serializacion
def _a_valor(dato: Any) -> dict:
    """Python -> el formato de valores que espera Turso."""
    if dato is None:
        return {"type": "null"}
    if isinstance(dato, bool):
        return {"type": "integer", "value": str(int(dato))}
    if isinstance(dato, int):
        # Turso transporta los enteros como cadena para no perder precision
        # en JSON con numeros de 64 bits.
        return {"type": "integer", "value": str(dato)}
    if isinstance(dato, float):
        return {"type": "float", "value": dato}
    if isinstance(dato, bytes):
        return {"type": "blob", "base64": base64.b64encode(dato).decode()}
    return {"type": "text", "value": str(dato)}


def _de_valor(valor: dict) -> Any:
    """El formato de Turso -> Python."""
    tipo = valor.get("type")
    if tipo == "null":
        return None
    if tipo == "integer":
        return int(valor["value"])
    if tipo == "float":
        return float(valor["value"])
    if tipo == "blob":
        return base64.b64decode(valor["base64"])
    return valor.get("value")


# ------------------------------------------------------------ filas/cursor
class Fila:
    """Compatible con sqlite3.Row en lo que usa storage.py."""

    __slots__ = ("_cols", "_vals")

    def __init__(self, cols: list[str], vals: list[Any]):
        self._cols = cols
        self._vals = vals

    def __getitem__(self, clave):
        if isinstance(clave, int):
            return self._vals[clave]
        try:
            return self._vals[self._cols.index(clave)]
        except ValueError:
            raise KeyError(clave) from None

    def keys(self) -> list[str]:      # lo que necesita dict(fila)
        return list(self._cols)

    def get(self, clave, defecto=None):
        try:
            return self[clave]
        except (KeyError, IndexError):
            return defecto

    def __contains__(self, clave) -> bool:
        return clave in self._cols

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def __repr__(self) -> str:
        return f"Fila({dict(zip(self._cols, self._vals))})"


class Cursor:
    """Resultado de un execute. Iterable, con fetchone() y rowcount."""

    def __init__(self, cols: list[str], filas: list[Fila], afectadas: int):
        self._filas = filas
        self._cols = cols
        self.rowcount = afectadas
        self._i = 0

    def __iter__(self) -> Iterator[Fila]:
        return iter(self._filas)

    def fetchone(self) -> "Fila | None":
        if self._i >= len(self._filas):
            return None
        self._i += 1
        return self._filas[self._i - 1]

    def fetchall(self) -> list[Fila]:
        return list(self._filas)


# --------------------------------------------------------------- conexion
def _url_http(url: str) -> str:
    """libsql://x.turso.io -> https://x.turso.io (lo que pega el CLI de Turso)."""
    url = url.strip().rstrip("/")
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    if url.startswith("wss://"):
        return "https://" + url[len("wss://"):]
    if url.startswith("ws://"):
        return "http://" + url[len("ws://"):]
    return url


def _solo_comentarios(sentencia: str) -> bool:
    """True si tras quitar los '--' no queda SQL que ejecutar."""
    utiles = [
        linea for linea in sentencia.splitlines()
        if linea.strip() and not linea.strip().startswith("--")
    ]
    return not utiles


class Conexion:
    def __init__(self, url: str, token: str):
        self._url = _url_http(url) + "/v2/pipeline"
        self._cabeceras = {"Authorization": f"Bearer {token}"}
        self._baton: str | None = None
        self._cliente = httpx.Client(timeout=TIMEOUT)
        self._cerrada = False

    # -- transporte -------------------------------------------------------
    def _pipeline(self, peticiones: list[dict]) -> list[dict]:
        cuerpo: dict[str, Any] = {"requests": peticiones}
        if self._baton:
            cuerpo["baton"] = self._baton
        try:
            respuesta = self._cliente.post(
                self._url, json=cuerpo, headers=self._cabeceras
            )
        except httpx.HTTPError as exc:
            raise ErrorTurso(
                f"No se pudo contactar la base de datos en Turso ({exc}). "
                "Revisa TURSO_DATABASE_URL y que la base siga activa."
            ) from exc

        if respuesta.status_code == 401:
            raise ErrorTurso(
                "Turso rechazo el token (401). El TURSO_AUTH_TOKEN esta mal o "
                "caduco: genera uno nuevo con 'turso db tokens create <base>'."
            )
        if respuesta.status_code >= 400:
            raise ErrorTurso(
                f"Turso devolvio {respuesta.status_code}: {respuesta.text[:300]}"
            )

        datos = respuesta.json()
        self._baton = datos.get("baton")

        resultados = []
        for item in datos.get("results", []):
            if item.get("type") == "error":
                mensaje = item.get("error", {}).get("message", "error desconocido")
                raise ErrorTurso(f"SQL rechazado por Turso: {mensaje}")
            resultados.append(item.get("response") or {})
        return resultados

    @staticmethod
    def _stmt(sql: str, args: Sequence[Any] = ()) -> dict:
        return {
            "type": "execute",
            "stmt": {"sql": sql, "args": [_a_valor(a) for a in args]},
        }

    @staticmethod
    def _a_cursor(respuesta: dict) -> Cursor:
        resultado = respuesta.get("result") or {}
        cols = [c.get("name") or "" for c in resultado.get("cols", [])]
        filas = [
            Fila(cols, [_de_valor(v) for v in fila])
            for fila in resultado.get("rows", [])
        ]
        return Cursor(cols, filas, resultado.get("affected_row_count", 0))

    # -- interfaz estilo sqlite3 ------------------------------------------
    def execute(self, sql: str, args: Sequence[Any] = ()) -> Cursor:
        respuestas = self._pipeline([self._stmt(sql, args)])
        return self._a_cursor(respuestas[0])

    def executemany(self, sql: str, filas: Sequence[Sequence[Any]]) -> Cursor:
        """Todas las filas viajan en un unico POST."""
        filas = list(filas)
        if not filas:
            return Cursor([], [], 0)
        respuestas = self._pipeline([self._stmt(sql, f) for f in filas])
        return self._a_cursor(respuestas[-1])

    def executescript(self, script: str) -> None:
        """
        Turso no acepta varias sentencias en un mismo execute, asi que el
        script se parte por ';'. Vale para el esquema (no hay ';' dentro de
        cadenas ni de comentarios).
        """
        sentencias = [s.strip() for s in script.split(";")]
        sentencias = [s for s in sentencias if s and not _solo_comentarios(s)]
        if sentencias:
            self._pipeline([self._stmt(s) for s in sentencias])

    def commit(self) -> None:
        """Cada sentencia ya se auto-confirma; existe por compatibilidad."""

    def rollback(self) -> None:
        """Sin transacciones multi-sentencia: nada que deshacer."""

    def close(self) -> None:
        if self._cerrada:
            return
        self._cerrada = True
        try:
            if self._baton:
                self._pipeline([{"type": "close"}])
        except ErrorTurso:
            pass  # cerrar es best-effort: la sesion caduca sola
        finally:
            self._cliente.close()


def conectar(url: str, token: str) -> Conexion:
    return Conexion(url, token)
