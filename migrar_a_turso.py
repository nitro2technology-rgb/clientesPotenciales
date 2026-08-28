"""
Sube data/leads.db a Turso, sin perder nada.

Cuando se usa
-------------
Una sola vez, antes del primer despliegue, para que la base de la nube arranque
con TODO lo que ya tienes en local (negocios, campanas a medias, geocache,
contador del dia). Despues puedes volver a ejecutarlo cuando quieras: es
idempotente, no duplica filas.

Uso
---
    .venv\\Scripts\\python.exe migrar_a_turso.py            # migra y comprueba
    .venv\\Scripts\\python.exe migrar_a_turso.py --verificar # solo compara

Antes hay que tener en el .env:
    TURSO_DATABASE_URL=libsql://...turso.io
    TURSO_AUTH_TOKEN=...

No borra ni toca el fichero local: solo lee.
"""
import sqlite3
import sys
from pathlib import Path

from app import turso
from app.config import settings
from app.storage import DB_PATH, ESQUEMA

LINEA = "=" * 66

# (tabla, cuantas columnas, como resolver un choque de clave primaria)
#
# - Los negocios se preservan tal cual: si ya estan en Turso, se dejan como
#   estan (IGNORE). Nunca se pisa un lead ya guardado.
# - Campanas, celdas y geocache se REPLACE porque lo de local es lo mas
#   reciente y es lo que queremos como punto de partida.
TABLAS = [
    ("negocios", 17, "OR IGNORE"),
    ("busquedas", 7, "OR IGNORE"),
    ("campanas", 11, "OR REPLACE"),
    ("celdas", 7, "OR REPLACE"),
    ("geocache", 4, "OR REPLACE"),
    ("uso_api", 2, "OR REPLACE"),
]

LOTE = 100  # sentencias por viaje de red


def _abrir_local() -> sqlite3.Connection:
    if not Path(DB_PATH).is_file():
        raise SystemExit(
            f"No existe la base local en {DB_PATH}.\n"
            "Nada que migrar: la app en Turso arrancara vacia y funcionara igual."
        )
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _abrir_remoto() -> turso.Conexion:
    if not settings.usa_turso:
        raise SystemExit(
            "Faltan TURSO_DATABASE_URL y/o TURSO_AUTH_TOKEN en el .env.\n"
            "Sacalos con:\n"
            "    turso db show --url <nombre-de-tu-base>\n"
            "    turso db tokens create <nombre-de-tu-base>"
        )
    return turso.conectar(settings.turso_database_url, settings.turso_auth_token)


def _contar(con, tabla: str) -> int:
    try:
        return con.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    except Exception:
        return 0


def _copiar(local: sqlite3.Connection, remoto: turso.Conexion, tabla: str,
            columnas: int, conflicto: str) -> int:
    filas = [tuple(f) for f in local.execute(f"SELECT * FROM {tabla}")]
    if not filas:
        print(f"  {tabla:<12} vacia en local, nada que subir")
        return 0

    marcadores = ",".join("?" * columnas)
    sql = f"INSERT {conflicto} INTO {tabla} VALUES ({marcadores})"

    for i in range(0, len(filas), LOTE):
        remoto.executemany(sql, filas[i:i + LOTE])
        hechas = min(i + LOTE, len(filas))
        print(f"  {tabla:<12} {hechas}/{len(filas)}", end="\r", flush=True)

    print(f"  {tabla:<12} {len(filas)} filas enviadas          ")
    return len(filas)


def _comparar(local: sqlite3.Connection, remoto: turso.Conexion) -> bool:
    print()
    print("  Tabla          local   Turso")
    print("  " + "-" * 30)
    todo_bien = True
    for tabla, _, _ in TABLAS:
        n_local = _contar(local, tabla)
        n_remoto = _contar(remoto, tabla)
        # Turso puede tener MAS filas (busquedas hechas ya desplegado): eso no
        # es un fallo. El fallo seria que faltara algo de lo local.
        marca = "OK" if n_remoto >= n_local else "FALTAN"
        if n_remoto < n_local:
            todo_bien = False
        print(f"  {tabla:<12} {n_local:>6}  {n_remoto:>6}   {marca}")
    return todo_bien


def main() -> int:
    solo_verificar = "--verificar" in sys.argv

    print(LINEA)
    print("  Migracion de leads.db  ->  Turso")
    print(LINEA)
    print(f"  Origen : {DB_PATH}")
    print(f"  Destino: {settings.turso_database_url or '(sin configurar)'}")
    print()

    local = _abrir_local()
    remoto = _abrir_remoto()

    try:
        if not solo_verificar:
            print("  Creando las tablas en Turso si no existen...")
            remoto.executescript(ESQUEMA)
            print("  Subiendo datos:")
            for tabla, columnas, conflicto in TABLAS:
                _copiar(local, remoto, tabla, columnas, conflicto)

        todo_bien = _comparar(local, remoto)
    finally:
        remoto.close()
        local.close()

    print()
    if todo_bien:
        print("  Todo tu historico esta en Turso. No se perdio nada.")
        print("  El fichero local sigue intacto por si acaso.")
    else:
        print("  !! Faltan filas en Turso. Vuelve a ejecutar el script.")
    print(LINEA)
    return 0 if todo_bien else 1


if __name__ == "__main__":
    raise SystemExit(main())
